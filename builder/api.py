"""
Per-item save API for the builder: each request saves one row, or the personal info.

The builder page calls these while the user edits (autosave), so a bad value in one field
never blocks saving the rest, and nothing is deleted unless the user removed it. The
validation and save rules come from ``builder.services``, the same ones the full-form POST
uses.

Every endpoint takes a multipart POST: fields named as in the builder forms (only the ones
that changed are needed for an update), an optional image, and ``lang=ar`` for Arabic
error messages. Answers are JSON:

    {"ok": true, "id": 12, "item": {...}}                     saved
    {"ok": false, "errors": {"<field>": ["message"]}}         400, nothing saved
    {"ok": false, "error": "signed_out"}                      401
"""
from functools import wraps

from django.db import transaction
from django.db.models.fields.files import FieldFile
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import translation
from django.views.decorators.http import require_POST

from builder import services
from builder.forms import PersonalInfoForm, ProjectForm
from core import activation, launch, onboarding
from core.models import Profile, Project

# Form messages written in English in builder.forms (Django's own ones are translated
# by activating Arabic while the form validates).
ERRORS_AR = {
    "Enter a valid phone number.": "أدخل رقم هاتف صحيحًا.",
    "Enter a valid graduation year.": "أدخل سنة تخرّج صحيحة.",
    launch.FIELD_ERRORS["booking_url"][0]: launch.FIELD_ERRORS["booking_url"][1],
    ProjectForm.INVALID_CATEGORY_ERROR: ProjectForm.INVALID_CATEGORY_ERROR_AR,
}


def _login_required_json(view):
    """Like login_required, but a signed-out request gets a 401 the page can show, not a redirect."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "error": "signed_out"}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _kind(key):
    kind = services.KINDS.get(key)
    if kind is None:
        raise Http404
    return kind


def _arabic(request):
    return request.POST.get("lang") == "ar"


def _posted(request, form_class, skip=()):
    """The form fields this request sent (an update sends only what changed)."""
    return {
        name: request.POST.get(name)
        for name in form_class.base_fields
        if name != "id" and name not in skip and name in request.POST
    }


def _image(request, name, arabic, error_key):
    """``(files, errors)``: the upload under ``name`` as a checked image, or an error for it."""
    upload = request.FILES.get(name) if name else None
    if not upload:
        return {}, None
    image = launch.clean_thumbnail(upload)
    if image is None:
        return {}, {name: [launch.field_error(error_key, arabic)]}
    return {name: image}, None


def _validate(form, arabic, posted, stored=None):
    """``(cleaned_data, errors)`` for a bound form.

    ``stored`` (an update) holds the row's saved values. A field the request didn't send
    that fails today's rules (saved under older ones) keeps its saved value instead of
    blocking the save: the user is editing something else.
    """
    with translation.override("ar" if arabic else "en"):
        form.is_valid()
        raw = form.errors.get_json_data()
    errors = {
        name: [ERRORS_AR.get(e["message"], e["message"]) if arabic else e["message"] for e in items]
        for name, items in raw.items()
    }
    blocking = errors if stored is None else {n: m for n, m in errors.items() if n in posted or n not in stored}
    if blocking:
        return None, blocking
    cleaned = dict(form.cleaned_data)
    for name in errors:
        cleaned[name] = stored[name]
    return cleaned, None


def _serialize(values):
    """Form values as JSON: image fields become their URL (or None)."""
    out = {}
    for name, value in values.items():
        if isinstance(value, FieldFile):
            value = value.url if value else None
        out[name] = value
    return out


def _invalid(user, kind, errors, reason="invalid"):
    activation.track(user, "builder_item_save_failed", kind=kind, fields=sorted(errors), reason=reason)
    return JsonResponse({"ok": False, "errors": errors}, status=400)


def _after_save(user):
    services.ensure_payment_row(user)
    services.publish_if_paid(user)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@require_POST
@_login_required_json
def save_personal(request):
    """Update name, title, contact, bio and booking link (any subset) and/or the picture."""
    user, arabic = request.user, _arabic(request)
    files, image_errors = _image(request, "picture", arabic, "picture")
    if image_errors:
        return _invalid(user, "personal", image_errors, reason="bad_image")

    posted = _posted(request, PersonalInfoForm, skip=("picture",))
    stored = services.personal_initial(user, arabic)
    form = PersonalInfoForm(data={**stored, **posted}, files=files)
    has_row = hasattr(user, "personal_info")
    cleaned, errors = _validate(form, arabic, posted, stored if has_row else None)
    if errors:
        return _invalid(user, "personal", errors)

    with transaction.atomic(), activation.source("builder"):
        services.save_personal(user, cleaned)
        _after_save(user)
    activation.track(user, "builder_item_saved", kind="personal", created=not has_row)

    item = services.personal_initial(user, arabic)
    profile = Profile.objects.filter(user=user).only("picture").first()
    item["picture"] = profile.picture if profile else None
    return JsonResponse({"ok": True, "item": _serialize(item)})


@require_POST
@_login_required_json
def create_item(request, kind):
    """Create one row. It must pass the same checks as a builder row."""
    spec, user, arabic = _kind(kind), request.user, _arabic(request)
    files, image_errors = _image(request, spec.image_field, arabic, "thumbnail")
    if image_errors:
        return _invalid(user, kind, image_errors, reason="bad_image")

    posted = _posted(request, spec.form, skip=(spec.image_field,))
    form = spec.form(data={**spec.create_defaults, **posted}, files=files, **services.form_kwargs(kind, user))
    cleaned, errors = _validate(form, arabic, posted)
    if errors:
        return _invalid(user, kind, errors)

    first_project = kind == "projects" and not Project.objects.filter(user=user).exists()
    with transaction.atomic(), activation.source("builder"):
        row, _ = services.save_row(user, kind, cleaned)
        _after_save(user)
    activation.track(user, "builder_item_saved", kind=kind, created=True)

    body = {"ok": True, "id": row.id, "item": _serialize(spec.to_initial(row))}
    if first_project:
        body["reveal_url"] = onboarding.reveal_url(user, arabic)
    return JsonResponse(body, status=201)


@require_POST
@_login_required_json
def update_item(request, kind, pk):
    """Update one of the user's rows with the fields sent; the others keep their saved values."""
    spec, user, arabic = _kind(kind), request.user, _arabic(request)
    row = get_object_or_404(spec.model, pk=pk, user=user)
    files, image_errors = _image(request, spec.image_field, arabic, "thumbnail")
    if image_errors:
        return _invalid(user, kind, image_errors, reason="bad_image")

    stored = spec.to_initial(row)
    stored.pop(spec.image_field, None)  # images only change through an upload
    posted = _posted(request, spec.form, skip=(spec.image_field,))
    form = spec.form(data={**stored, **posted}, files=files, **services.form_kwargs(kind, user))
    cleaned, errors = _validate(form, arabic, posted, stored)
    if errors:
        return _invalid(user, kind, errors)

    with transaction.atomic(), activation.source("builder"):
        row, _ = services.save_row(user, kind, cleaned, instance=row)
        _after_save(user)
    activation.track(user, "builder_item_saved", kind=kind, created=False)
    return JsonResponse({"ok": True, "id": row.id, "item": _serialize(spec.to_initial(row))})


@require_POST
@_login_required_json
def delete_item(request, kind, pk):
    """Delete one of the user's rows."""
    spec, user = _kind(kind), request.user
    row = get_object_or_404(spec.model, pk=pk, user=user)
    row.delete()
    activation.track(user, "builder_item_deleted", kind=kind)
    return JsonResponse({"ok": True, "id": pk})
