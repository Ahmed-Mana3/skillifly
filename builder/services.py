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


# Host (or host suffix) -> the name a link shows under. Mirrors PLATFORMS in builder_v2.js.
PLATFORMS = (
    ("instagram.com", "Instagram"), ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
    ("tiktok.com", "TikTok"), ("vimeo.com", "Vimeo"), ("behance.net", "Behance"),
    ("linkedin.com", "LinkedIn"), ("facebook.com", "Facebook"), ("fb.com", "Facebook"),
    ("x.com", "X"), ("twitter.com", "X"), ("threads.net", "Threads"), ("wa.me", "WhatsApp"),
    ("whatsapp.com", "WhatsApp"), ("t.me", "Telegram"), ("dribbble.com", "Dribbble"),
    ("artstation.com", "ArtStation"), ("github.com", "GitHub"), ("snapchat.com", "Snapchat"),
    ("pinterest.com", "Pinterest"), ("calendly.com", "Calendly"), ("drive.google.com", "Google Drive"),
)


def platform_from_url(url):
    """'https://www.instagram.com/sara' -> 'Instagram'; unknown hosts give their name ('sara.studio')."""
    from urllib.parse import urlsplit
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = (urlsplit(raw).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    for domain, name in PLATFORMS:
        if host == domain or host.endswith("." + domain):
            return name
    return host[:254]


def link_title(url, arabic=False):
    """A title for a video added by link only: the video's own title, or a friendly default."""
    from core import oembed
    meta = oembed.fetch(url) if url else None  # usually cached by the builder's live preview
    if meta is not None and meta.ok and meta.title:
        return meta.title[:500]
    return onboarding.default_video_title(arabic)


def attach_link_thumbnail(project_id):
    """Give a video without a cover image the thumbnail of its link. Never raises."""
    from core import oembed
    try:
        project = Project.objects.filter(pk=project_id).first()
        if project is None or project.image or not project.url:
            return
        meta = oembed.fetch(project.url)
        thumb = oembed.download_thumbnail(meta) if meta.ok else None
        if thumb:
            project.image.save(thumb.name, thumb, save=True)
    except Exception:
        import logging
        logging.getLogger("core").debug("attach_link_thumbnail failed for %s", project_id, exc_info=True)


def reorder_projects(user, ids):
    """Put the user's videos in this order. Videos not listed keep their order, after these."""
    own = list(Project.objects.filter(user=user).order_by("order", "id").values_list("id", flat=True))
    wanted = [i for i in dict.fromkeys(ids) if i in set(own)]
    final = wanted + [i for i in own if i not in set(wanted)]
    with transaction.atomic():
        for position, project_id in enumerate(final):
            Project.objects.filter(pk=project_id, user=user).exclude(order=position).update(order=position)
    return final


def skill_presets(arabic=False):
    """The launch checklist's skill chips for the builder: label in the page language, plus
    every name that counts as this skill (English and Arabic), lower-cased for matching."""
    from core.launch import SKILL_GROUPS
    return [
        {
            "title": group["ar" if arabic else "en"],
            "chips": [
                {"label": ar if arabic else en, "names": "|".join(sorted({en.casefold(), ar.casefold()}))}
                for en, ar in group["skills"]
            ],
        }
        for group in SKILL_GROUPS
    ]


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
        to_fields=lambda data, categories: {
            "platform": (data.get("name") or "").strip() or platform_from_url(data["url"]),
            "url": data["url"],
        },
    ),
    "creators": Kind(
        model=Creator,
        form=CreatorForm,
        to_initial=lambda c: {"id": c.id, "name": c.name, "image": c.image, "url": c.url},
        to_fields=_creator_fields,
        image_field="image",
    ),
}


def form_kwargs(key, user, arabic=False):
    """Extra form arguments: projects check collection ownership against the user, in the page's language."""
    return {"user": user, "arabic": arabic} if key == "projects" else {}


# ---------------------------------------------------------------------------
# Saving rows
# ---------------------------------------------------------------------------

def save_row(user, key, data, instance=None, categories=None, arabic=False):
    """Create a row from valid form data, or update ``instance`` in place.

    Returns ``(row, created)``. Only changed fields are written. A video saved without a
    title gets its link's title; one with a new link and no cover image gets the link's
    thumbnail once the save has committed.
    """
    kind = KINDS[key]
    if categories is None:
        categories = category_map(user) if key == "projects" else {}
    fields = kind.to_fields(data, categories)
    if key == "projects" and not (fields.get("title") or "").strip():
        fields["title"] = link_title(fields.get("url"), arabic)

    if instance is None:
        row, created, link_changed = kind.model.objects.create(user=user, **fields), True, True
    else:
        row, created = instance, False
        link_changed = key == "projects" and fields.get("url") != instance.url
        changed = False
        for name, value in fields.items():
            if getattr(instance, name) != value:
                setattr(instance, name, value)
                changed = True
        if changed:
            instance.save()

    if key == "projects" and link_changed and row.url:
        if row.image and is_link_thumbnail(row.image):
            # The old link's thumbnail would show the wrong video; an uploaded image stays.
            row.image = None
            row.save(update_fields=["image"])
        if not row.image:
            transaction.on_commit(lambda pk=row.pk: attach_link_thumbnail(pk))
    return row, created


def is_link_thumbnail(image):
    """True for an image fetched from a video link (core.oembed names them oembed_*), not one the user uploaded."""
    return "oembed_" in (getattr(image, "name", "") or "").rsplit("/", 1)[-1]


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


def save_formset(user, key, formset, categories, arabic=False):
    """Apply one builder formset: update or create its rows, delete the removed ones."""
    existing = {row.id: row for row in KINDS[key].model.objects.filter(user=user)}
    for form in formset:
        data = form.cleaned_data
        if not data or data.get("DELETE"):
            continue
        save_row(user, key, data, existing.get(data.get("id")), categories, arabic=arabic)
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


def title_confirmed_after(previous, title, confirm_title):
    """Whether the saved title counts as the user's choice.

    It does when they set it this time (``confirm_title``: they typed in the title field or
    pressed "Keep this title"), when it isn't the signup default, or when they had already
    kept this same title. The default carried along by an unrelated save doesn't count.
    """
    if confirm_title or not onboarding.is_placeholder_title(title):
        return True
    return bool(previous and previous.title_confirmed and (previous.title or "").strip() == (title or "").strip())


def save_personal(user, data, confirm_title=False):
    """Save valid personal-info form data; a new picture goes on the Profile."""
    previous = PersonalInfo.objects.filter(user=user).first()
    info, _ = PersonalInfo.objects.update_or_create(
        user=user,
        defaults={
            "full_name": data["fullname"],
            "title": data["title"],
            "title_confirmed": title_confirmed_after(previous, data["title"], confirm_title),
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
