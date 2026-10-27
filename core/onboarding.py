"""
Editor onboarding v2: first-run helpers.

Everything the welcome flow, the dashboard first-run state, the reveal bar and
the builder pre-fill share lives here so the views stay thin. See
ONBOARDING_V2_PLAN.md.
"""
import logging

from django.core.cache import cache
from django.urls import reverse

from core import activation
from core.models import PersonalInfo, Profile, Project, SiteSettings, Theme

logger = logging.getLogger('core')

MAX_LINKS = 3
PREVIEW_LOOKUPS_PER_HOUR = 30
SIGNUP_LIMIT_PER_HOUR = 10

# Themes whose builder panel requires a profile picture (builder.html:126);
# a brand-new user has none, so they must not be assigned automatically.
PICTURE_REQUIRED_THEMES = frozenset({'animated', 'animated dark', 'creative white'})
FALLBACK_THEME = ('video editor', 'creative')

DEFAULT_TITLES = {  # normalized theme category -> (English, Arabic)
    'video_editor': ('Video Editor', 'مونتير فيديو'),
    'developer': ('Software Developer', 'مطوّر برمجيات'),
    'student': ('Student', 'طالب'),
}
PLACEHOLDER_TITLES = frozenset(t for pair in DEFAULT_TITLES.values() for t in pair)
_PLACEHOLDER_KEYS = frozenset(t.casefold() for t in PLACEHOLDER_TITLES)


def is_placeholder_title(title):
    """The title filled in at signup ('Video Editor', any case), not one the user wrote."""
    return (title or '').strip().casefold() in _PLACEHOLDER_KEYS


def title_counts(info):
    """Whether the portfolio's title is the user's own: anything they wrote, or the
    signup default once they kept it (PersonalInfo.title_confirmed)."""
    title = (info.title or '').strip() if info else ''
    return bool(title) and (info.title_confirmed or not is_placeholder_title(title))
DEFAULT_VIDEO_TITLES = ('My video', 'فيديو من أعمالي')

ERROR_MESSAGES = {
    'invalid': (
        'Paste a full link, starting with https://',
        'الصق رابطًا كاملًا يبدأ بـ https://',
    ),
    'private': (
        'This video is private. Set it to Unlisted, then paste the link again.',
        'هذا الفيديو خاص. اجعله «غير مُدرج» ثم الصق الرابط مرة أخرى.',
    ),
    'not_found': (
        "We couldn't find that video. Check the link and try again.",
        'لم نجد هذا الفيديو. تأكد من الرابط وحاول مرة أخرى.',
    ),
    'lookup_failed': (
        "Couldn't load a preview, but you can still add it. Just type a title.",
        'تعذّر تحميل المعاينة، لكن يمكنك إضافته. فقط اكتب عنوانًا.',
    ),
    'rate_limited': (
        'Too many lookups. Please wait a little and try again.',
        'محاولات كثيرة. انتظر قليلًا ثم حاول مرة أخرى.',
    ),
}


# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------

def _site_settings():
    return SiteSettings.objects.first()


def onboarding_enabled():
    row = _site_settings()
    return bool(row and row.onboarding_v2_enabled)


def defer_verification_enabled():
    row = _site_settings()
    return bool(row and row.defer_email_verification)


def nudges_enabled():
    row = _site_settings()
    return bool(row and row.nudges_enabled)


# ---------------------------------------------------------------------------
# Email verification (deferred flow)
# ---------------------------------------------------------------------------

def needs_email_verification(user):
    """True only for accounts that were let in before verifying their email.

    Legacy and Google users have no EmailAddress row (or a verified one), so they
    are never gated.
    """
    from allauth.account.models import EmailAddress
    rows = EmailAddress.objects.filter(user=user)
    return rows.filter(verified=False).exists() and not rows.filter(verified=True).exists()


def signup_rate_limited(request):
    """Cap signups per IP per hour. Only enforced when verification is deferred,
    because that is when a signup no longer proves ownership of an inbox."""
    if not defer_verification_enabled():
        return False
    from analytics.views import get_client_ip
    key = f'signup-rate:{get_client_ip(request) or "unknown"}'
    count = cache.get(key, 0)
    if count >= SIGNUP_LIMIT_PER_HOUR:
        return True
    cache.set(key, count + 1, 3600)
    return False


# ---------------------------------------------------------------------------
# Defaults for a brand-new editor
# ---------------------------------------------------------------------------

def _category_key(profile):
    category = getattr(getattr(getattr(profile, 'theme', None), 'category', None), 'name', '') or 'Video Editor'
    return category.lower().replace(' ', '_')


def default_title(user, arabic=False):
    profile = getattr(user, 'profile', None)
    en, ar = DEFAULT_TITLES.get(_category_key(profile), DEFAULT_TITLES['video_editor'])
    return ar if arabic else en


def default_video_title(arabic=False):
    return DEFAULT_VIDEO_TITLES[1 if arabic else 0]


def default_editor_theme():
    row = SiteSettings.objects.select_related('default_editor_theme__category').first()
    theme = row.default_editor_theme if row else None
    if theme and theme.name.lower() not in PICTURE_REQUIRED_THEMES:
        return theme
    return Theme.objects.filter(
        category__name__iexact=FALLBACK_THEME[0], name__iexact=FALLBACK_THEME[1],
    ).first()


LOOK_CHOICE_NAMES = ('creative', 'pro', 'minimal')  # photo-free, most-used editor themes


def look_choices():
    """Themes offered as one-tap "Try another look" chips on the reveal bar."""
    from django.db.models import Q
    query = Q()
    for name in LOOK_CHOICE_NAMES:
        query |= Q(name__iexact=name)
    return Theme.objects.filter(query, category__name__iexact='video editor').order_by('-use_num')


def ensure_default_theme(user):
    """Give an editor without a theme the default one. Idempotent; never raises."""
    try:
        if not activation.is_editor(user):
            return None
        profile, _ = Profile.objects.get_or_create(user=user)
        if profile.theme_id:
            return profile.theme
        theme = default_editor_theme()
        if theme is None:
            logger.warning('No default editor theme available')
            return None
        profile.theme = theme
        profile.save(update_fields=['theme', 'updated_at'])
        # Drop a stale cached profile (theme=None) from the request's user object.
        user._state.fields_cache.pop('profile', None)
        # Theme.use_num is deliberately not bumped: auto-assignment isn't a user choice.
        return theme
    except Exception:
        logger.exception('ensure_default_theme failed for user %s', getattr(user, 'pk', None))
        return None


def ensure_personal_info(user, arabic=False):
    """Create PersonalInfo from signup data so the builder never asks for it first."""
    info, _ = PersonalInfo.objects.get_or_create(user=user, defaults={
        'full_name': user.get_full_name().strip() or user.username,
        'title': default_title(user, arabic),
        'email': '', 'phone': '', 'bio': '',
    })
    return info


def personal_initial(user, personal_info, arabic=False):
    """Initial values for the builder's personal-info form."""
    if personal_info:
        return {
            'fullname': personal_info.full_name,
            'title': personal_info.title,
            'email': personal_info.email,
            'phone': personal_info.phone,
            'bio': personal_info.bio,
            'booking_url': personal_info.booking_url,
        }
    # The contact email is deliberately not pre-filled: it is shown publicly.
    return {
        'fullname': user.get_full_name().strip(),
        'title': default_title(user, arabic),
    }


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def welcome_url(arabic=False, **params):
    from urllib.parse import urlencode
    url = reverse('arabic_welcome' if arabic else 'welcome')
    return f'{url}?{urlencode(params)}' if params else url


def reveal_url(user, arabic=False):
    url = reverse('preview', kwargs={'username': user.username}) + '?welcome=1'
    return url + '&lang=ar' if arabic else url


def demo_preview_url():
    theme = default_editor_theme()
    slug = (theme.name if theme else 'creative').lower().replace(' ', '_')
    return f'/preview/{slug}/?embed=1'


def error_message(code, arabic=False):
    pair = ERROR_MESSAGES.get(code) or ERROR_MESSAGES['lookup_failed']
    return pair[1 if arabic else 0]


def allow_preview(request):
    """Session-scoped cap on link lookups (30/hour) so the endpoint can't be used as a proxy."""
    key = 'preview_lookups'
    import time
    now = time.time()
    stamps = [t for t in request.session.get(key, []) if now - t < 3600]
    if len(stamps) >= PREVIEW_LOOKUPS_PER_HOUR:
        request.session[key] = stamps
        return False
    stamps.append(now)
    request.session[key] = stamps
    return True


# ---------------------------------------------------------------------------
# First projects
# ---------------------------------------------------------------------------

def create_projects_from_links(user, data, arabic=False, source='welcome', limit=MAX_LINKS, thumbnails=None):
    """Create up to ``limit`` projects from the welcome form.

    ``data`` is a QueryDict with repeated ``url`` / ``title`` / ``video_type``
    fields. ``thumbnails`` optionally maps a row index to an image file the user
    chose; it is used instead of the looked-up one. Returns
    ``(created_projects, {row_index: error_code})``.
    """
    from core import oembed

    urls = data.getlist('url')[:limit]
    titles = data.getlist('title')
    types = data.getlist('video_type')
    existing = set(Project.objects.filter(user=user).values_list('url', flat=True))
    created, errors = [], {}

    with activation.source(source):
        for i, raw in enumerate(urls):
            if not (raw or '').strip():
                continue
            url = oembed.normalize_url(raw)
            if not url:
                errors[i] = 'invalid'
                continue
            if url in existing:
                continue  # double-submit, or already in the portfolio
            meta = oembed.fetch(url)  # usually a cache hit from the live preview
            if oembed.is_hard_failure(meta):
                errors[i] = meta.error  # private / nonexistent: it would never play for visitors
                continue
            if meta.ok and meta.url:
                url = meta.url
                if url in existing:
                    continue
            title = (titles[i] if i < len(titles) else '').strip()[:500] or meta.title or default_video_title(arabic)
            vtype = types[i] if i < len(types) and types[i] in ('long', 'reel') else meta.video_type
            project = Project(user=user, title=title, url=url, video_type=vtype)
            thumb = (thumbnails or {}).get(i) or (oembed.download_thumbnail(meta) if meta.ok else None)
            if thumb:
                project.image.save(thumb.name, thumb, save=False)
            project.save()
            existing.add(url)
            created.append(project)
    return created, errors


# ---------------------------------------------------------------------------
# "Next best step" card on the dashboard
# ---------------------------------------------------------------------------

NEXT_STEP_COPY = {
    'videos': {
        'en': ('Add more videos',
               'Clients usually decide after seeing 3 to 6 strong pieces. You have {have}.',
               'Add videos'),
        'ar': ('أضف فيديوهات أخرى',
               'يقرّر العملاء عادةً بعد مشاهدة 3 إلى 6 أعمال قوية. لديك {have}.',
               'أضف فيديوهات'),
    },
    'contact': {
        'en': ('Add WhatsApp so clients can reach you in one tap',
               'Paste your WhatsApp number or a Calendly link. It becomes a booking button on your portfolio.',
               'Add contact'),
        'ar': ('أضف واتساب ليتواصل معك العملاء بضغطة واحدة',
               'الصق رقم واتساب أو رابط Calendly ليصبح زر حجز في معرضك.',
               'أضف وسيلة تواصل'),
    },
    'bio': {
        'en': ('Write your bio in one click',
               "We'll draft a short bio from your videos and skills. You can edit it anytime.",
               'Write my bio'),
        'ar': ('اكتب نبذتك الشخصية بضغطة واحدة',
               'سنكتب لك نبذة قصيرة اعتمادًا على فيديوهاتك ومهاراتك، ويمكنك تعديلها في أي وقت.',
               'اكتب نبذتي'),
    },
    'skills': {
        'en': ('Add the software you use',
               'Premiere, After Effects, DaVinci Resolve… clients search by tools.',
               'Add skills'),
        'ar': ('أضف البرامج التي تستخدمها',
               'بريميير، أفتر إفكتس، دافنشي ريزولف… يبحث العملاء بحسب الأدوات.',
               'أضف المهارات'),
    },
}


def next_step(user, projects_count, arabic=False):
    """The single most useful thing this editor can do next, or None when they're set.

    Order: videos (the thing clients judge) -> a way to be contacted -> bio -> skills.
    """
    info = PersonalInfo.objects.filter(user=user).first()
    has_contact = bool(info and ((info.booking_url or '').strip() or (info.phone or '').strip()))
    has_bio = bool(info and (info.bio or '').strip())
    builder = reverse('arabic_update_portfolio' if arabic else 'update_portfolio')
    lang = 'ar' if arabic else 'en'

    def result(key, url, post=False, **fmt):
        title, body, cta = NEXT_STEP_COPY[key][lang]
        return {'key': key, 'title': title, 'body': body.format(**fmt), 'cta': cta, 'url': url, 'post': post}

    if projects_count < 3:
        if arabic:
            have = {0: 'لا شيء بعد', 1: 'فيديو واحد', 2: 'فيديوهان'}[projects_count]
        else:
            have = {0: 'none yet', 1: '1 so far', 2: '2 so far'}[projects_count]
        url = welcome_url(arabic, add=1) if onboarding_enabled() else builder + '#projects'
        return result('videos', url, have=have)
    if not has_contact:
        return result('contact', builder + '#identity')
    if not has_bio:
        return result('bio', reverse('ai_bio_draft'), post=True)
    if not user.skills.exists():
        return result('skills', builder + '#skills')
    return None


# ---------------------------------------------------------------------------
# "Client-ready" checklist (reveal bar + dashboard)
# ---------------------------------------------------------------------------

def client_ready(user):
    """The three things that make a portfolio worth sending to a client."""
    info = PersonalInfo.objects.filter(user=user).first()
    ready = {
        'videos': Project.objects.filter(user=user).count() >= 3,
        'title': title_counts(info),
        'contact': bool(info and ((info.booking_url or '').strip() or (info.phone or '').strip())),
    }
    ready['count'] = sum(1 for k in ('videos', 'title', 'contact') if ready[k])
    return ready
