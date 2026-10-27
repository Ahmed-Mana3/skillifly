"""
Builder save rules, shared by the full-form POST (``views.save_portfolio_data``) and the
per-item save API (``builder.api``).

Each kind of portfolio row has one ``Kind`` in ``KINDS``: its model, the builder form that
validates it, how a saved row becomes form values (``to_initial``) and how a valid form
becomes model fields (``to_fields``). Both save paths go through these, so a rule changes
in one place.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from django.db import transaction

from builder.forms import (
    CreatorForm,
    EducationForm,
    ExperienceForm,
    LinkForm,
    ProjectForm,
    SkillForm,
)
from core import activation, onboarding
from core.models import (
    Creator,
    Education,
    Experience,
    Link,
    PersonalInfo,
    Profile,
    Project,
    ProjectCategory,
    Skill,
    UserPayment,
)


def parse_month_year(value):
    """'2024-03' -> date(2024, 3, 1); anything else -> None."""
    if not value:
        return None
    try:
        y, m = map(int, value.split("-"))
        return date(y, m, 1)
    except (ValueError, AttributeError):
        return None


def category_map(user):
    """The user's collections by id, read once per save."""
    return {c.id: c for c in ProjectCategory.objects.filter(user=user)}


def category_for(category_id, categories):
    if not category_id:
        return None
    try:
        return categories.get(int(category_id))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Kind:
    model: type
    form: type
    to_initial: Callable  # (row) -> form values, including "id"
    to_fields: Callable   # (cleaned_data, categories) -> model fields
    image_field: Optional[str] = None  # form field holding an image upload, if any
    create_defaults: dict = field(default_factory=dict)  # form values a new row starts from


def _project_fields(data, categories):
    fields = {
        "title": data["name"],
        "url": data.get("url"),
        "details": data.get("description"),
        "video_type": data.get("video_type") or "long",
        "category": category_for(data.get("category_id"), categories),
    }
    if data.get("thumbnail"):
        fields["image"] = data["thumbnail"]  # no new upload keeps the current image
    return fields


def _experience_fields(data, categories):
    end_date = parse_month_year(data.get("end"))
    return {
        "title": data["title"],
        "company": data["company"],
        "start_date": parse_month_year(data.get("start")) or date.today(),
        "end_date": end_date,
        "still_working": not end_date,
        "duration": 0.0,
        "details": data.get("description", ""),
    }


def _creator_fields(data, categories):
    fields = {"name": data["name"], "url": data.get("url")}
    if data.get("image"):
        fields["image"] = data["image"]
    return fields


KINDS = {
    "skills": Kind(
        model=Skill,
        form=SkillForm,
        to_initial=lambda s: {"id": s.id, "skill": s.name},
        to_fields=lambda data, categories: {"name": data["skill"]},
    ),
    "education": Kind(
        model=Education,
        form=EducationForm,
        to_initial=lambda e: {
            "id": e.id,
            "school": e.school,
            "degree": e.degree,
            "field": e.field,
            "year": e.grade_year.year,
        },
        to_fields=lambda data, categories: {
            "school": data["school"],
            "degree": data["degree"],
            "field": data["field"],
            "grade_year": date(data["year"], 1, 1),
        },
    ),
    "experience": Kind(
        model=Experience,
        form=ExperienceForm,
        to_initial=lambda e: {
            "id": e.id,
            "title": e.title,
            "company": e.company,
            "start": e.start_date.strftime("%Y-%m") if e.start_date else "",
            "end": e.end_date.strftime("%Y-%m") if e.end_date else "",
            "description": e.details,
        },
        to_fields=_experience_fields,
    ),
    "projects": Kind(
        model=Project,
        form=ProjectForm,
        to_initial=lambda p: {
            "id": p.id,
            "name": p.title,
            "url": p.url,
            "description": p.details,
            "video_type": p.video_type,
            "thumbnail": p.image,
            "category_id": p.category_id,
        },
        to_fields=_project_fields,
        image_field="thumbnail",
        create_defaults={"video_type": "long"},
    ),
    "links": Kind(
        model=Link,
        form=LinkForm,
        to_initial=lambda l: {"id": l.id, "name": l.platform, "url": l.url},
        to_fields=lambda data, categories: {"platform": data["name"], "url": data["url"]},
    ),
    "creators": Kind(
        model=Creator,
        form=CreatorForm,
        to_initial=lambda c: {"id": c.id, "name": c.name, "image": c.image, "url": c.url},
        to_fields=_creator_fields,
        image_field="image",
    ),
}


def form_kwargs(key, user):
    """Extra form arguments: projects check collection ownership against the user."""
    return {"user": user} if key == "projects" else {}


# ---------------------------------------------------------------------------
# Saving rows
# ---------------------------------------------------------------------------

def save_row(user, key, data, instance=None, categories=None):
    """Create a row from valid form data, or update ``instance`` in place.

    Returns ``(row, created)``. Only changed fields are written.
    """
    kind = KINDS[key]
    if categories is None:
        categories = category_map(user) if key == "projects" else {}
    fields = kind.to_fields(data, categories)
    if instance is None:
        return kind.model.objects.create(user=user, **fields), True
    changed = False
    for name, value in fields.items():
        if getattr(instance, name) != value:
            setattr(instance, name, value)
            changed = True
    if changed:
        instance.save()
    return instance, False


def deleted_ids(formset):
    """Ids of saved rows the user removed: the builder ticks their hidden DELETE box.

    Only these rows are deleted. A row missing from the POST is left alone, since it
    may have been added after the builder loaded (launch pages, the agent, another tab).
    """
    ids = set()
    for form in formset:
        data = getattr(form, "cleaned_data", None) or {}
        if data.get("DELETE") and data.get("id"):
            ids.add(data["id"])
    return ids


def save_formset(user, key, formset, categories):
    """Apply one builder formset: update or create its rows, delete the removed ones."""
    existing = {row.id: row for row in KINDS[key].model.objects.filter(user=user)}
    for form in formset:
        data = form.cleaned_data
        if not data or data.get("DELETE"):
            continue
        save_row(user, key, data, existing.get(data.get("id")), categories)
    for row_id in deleted_ids(formset):
        row = existing.get(row_id)
        if row is not None:
            row.delete()


# ---------------------------------------------------------------------------
# Personal info
# ---------------------------------------------------------------------------

def personal_initial(user, arabic=False):
    """The personal-info form's current values (signup defaults for a brand-new user)."""
    return onboarding.personal_initial(user, PersonalInfo.objects.filter(user=user).first(), arabic)


def track_profile_fields_added(user, previous, personal_data):
    """Record which personal-info fields went from empty/placeholder to filled in."""
    def filled(value):
        return bool((value or "").strip())

    added = []
    for name in ("bio", "booking_url", "phone"):
        if filled(personal_data.get(name)) and not (previous and filled(getattr(previous, name, ""))):
            added.append(name)
    new_title = (personal_data.get("title") or "").strip()
    old_title = (previous.title or "").strip() if previous else ""
    if new_title and new_title not in onboarding.PLACEHOLDER_TITLES and (
        not old_title or old_title in onboarding.PLACEHOLDER_TITLES
    ):
        added.append("title")
    for name in added:
        transaction.on_commit(
            lambda f=name: activation.track(user, "profile_field_added", field=f, source="builder")
        )


def save_personal(user, data):
    """Save valid personal-info form data; a new picture goes on the Profile."""
    previous = PersonalInfo.objects.filter(user=user).first()
    info, _ = PersonalInfo.objects.update_or_create(
        user=user,
        defaults={
            "full_name": data["fullname"],
            "title": data["title"],
            "email": data["email"],
            "phone": data["phone"],
            "bio": data["bio"],
            "booking_url": data.get("booking_url"),
        },
    )
    track_profile_fields_added(user, previous, data)

    if data.get("picture"):
        profile, _ = Profile.objects.get_or_create(user=user)
        had_picture = bool(profile.picture)
        profile.picture = data["picture"]
        profile.save()
        if not had_picture:
            transaction.on_commit(
                lambda: activation.track(user, "profile_field_added", field="picture", source="builder")
            )
    return info


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------

def autosave_enabled():
    """Whether the builder page saves as the user types (SiteSettings.builder_autosave_enabled)."""
    from core.models import SiteSettings
    row = SiteSettings.objects.only("builder_autosave_enabled").first()
    return bool(row and row.builder_autosave_enabled)  # the field defaults to off


# ---------------------------------------------------------------------------
# After any builder save
# ---------------------------------------------------------------------------

def ensure_payment_row(user):
    """The rest of the site expects every builder user to have a UserPayment row."""
    if not UserPayment.objects.filter(user=user).exists():
        UserPayment.objects.create(user=user)


def publish_if_paid(user):
    """A builder save makes the portfolio public while the user's plan is active."""
    payment = UserPayment.objects.filter(user=user, status="paid").last()
    if payment and payment.is_active:
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_public = True
        profile.save()
