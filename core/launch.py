"""
Launch checklist: the full-screen, step-by-step setup a new editor sees right after signup.

Four steps, each worth XP: about you -> first video -> theme -> skills. They happen on
small single-purpose pages (the theme on the existing themes gallery), each returning to
the checklist with a small celebration. The XP adds up to 100, so XP is also the progress
percentage; at 100 XP the flow is finished and the editor can view their portfolio or go
to the dashboard. Publishing (payment) is offered from there, not as a step.

State lives on UserAccount (``launch_status``, ``launch_theme_picked``). Everything else
is derived from the portfolio itself, so progress made elsewhere (builder, AI agent)
counts too. Switched by ``SiteSettings.launch_checklist_enabled``.
"""
import io
import logging
import re
from uuid import uuid4

from django.core.files.base import ContentFile
from django.urls import reverse

from core import activation
from core.models import PersonalInfo, Profile, Project, SiteSettings, Skill, UserPayment

logger = logging.getLogger('core')

STEPS = ('personal', 'project', 'theme', 'skills')
# The video is what clients judge, so it is worth the most. Adds up to 100.
XP = {'personal': 25, 'project': 35, 'theme': 15, 'skills': 25}
XP_TOTAL = sum(XP.values())

# Icon tile tint per step (dashboard .tint-* classes).
STEP_TINTS = {'personal': 'violet', 'project': 'blue', 'theme': 'fuchsia', 'skills': 'amber'}

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_SKILLS = 20
MAX_SKILL_LENGTH = 60

STEP_COPY = {
    'personal': {
        'icon': 'user-round',
        'en': {'title': 'Introduce yourself', 'time': '1 min', 'cta': "Let's go", 'cheer': 'Nice to meet you!',
               'lead': "Clients like to know who's behind the edits. This takes about a minute.",
               'body': "Your name, title and photo, so clients know who they're hiring."},
        'ar': {'title': 'عرّف بنفسك', 'time': 'دقيقة واحدة', 'cta': 'هيا نبدأ', 'cheer': 'تشرّفنا بمعرفتك!',
               'lead': 'يحب العملاء معرفة من يقف وراء المونتاج. الأمر يستغرق دقيقة.',
               'body': 'اسمك ومسمّاك الوظيفي وصورتك، ليعرف العملاء من سيعملون معه.'},
    },
    'project': {
        'icon': 'clapperboard',
        'en': {'title': 'Add your best video', 'time': '1 min', 'cta': 'Add a video', 'cheer': 'Your first video is in!',
               'lead': "Paste a link to your best work. We'll grab the title and thumbnail for you.",
               'body': 'Paste a YouTube, Vimeo, TikTok, Instagram or Drive link. We grab the title and thumbnail.'},
        'ar': {'title': 'أضف أفضل فيديو لك', 'time': 'دقيقة واحدة', 'cta': 'أضف فيديو', 'cheer': 'أضفت أول فيديو!',
               'lead': 'الصق رابط أفضل أعمالك وسنجلب العنوان والصورة المصغّرة تلقائيًا.',
               'body': 'الصق رابط يوتيوب أو فيميو أو تيك توك أو إنستجرام أو درايف، ونحن نجلب العنوان والصورة.'},
    },
    'theme': {
        'icon': 'palette',
        'en': {'title': 'Pick your theme', 'time': '30 sec', 'cta': 'Browse themes', 'cheer': 'Looking sharp!',
               'lead': 'Choose the theme that fits your style. You can switch anytime.',
               'body': 'Choose the theme that fits your style. You can switch anytime.'},
        'ar': {'title': 'اختر تصميمك', 'time': '30 ثانية', 'cta': 'تصفّح التصاميم', 'cheer': 'اختيار رائع!',
               'lead': 'اختر التصميم الذي يناسب أسلوبك. يمكنك تغييره في أي وقت.',
               'body': 'اختر التصميم الذي يناسب أسلوبك. يمكنك تغييره في أي وقت.'},
    },
    'skills': {
        'icon': 'sparkles',
        'en': {'title': 'Show your skills', 'time': '30 sec', 'cta': 'Pick skills', 'cheer': 'Skills on show!',
               'lead': "Tap everything you're great at. Clients look for editors by the tools they use.",
               'body': 'Tap the software and crafts you are great at. Clients search by tools.'},
        'ar': {'title': 'أبرز مهاراتك', 'time': '30 ثانية', 'cta': 'اختر مهاراتك', 'cheer': 'مهاراتك ظاهرة الآن!',
               'lead': 'اختر كل ما تتقنه. العملاء يبحثون عن المونتير بحسب البرامج والمهارات.',
               'body': 'اختر البرامج والمهارات التي تتقنها. العملاء يبحثون بحسب الأدوات.'},
    },
}

TITLE_SUGGESTIONS = {
    'en': ('Video Editor', 'Motion Designer', 'Colorist', 'Content Creator', 'Filmmaker', 'YouTube Editor'),
    'ar': ('مونتير فيديو', 'مصمم موشن جرافيك', 'مصحح ألوان', 'صانع محتوى', 'صانع أفلام', 'مونتير يوتيوب'),
}

# (English, Arabic) per preset. Brand names are the same in both.
SKILL_GROUPS = (
    {
        'key': 'software',
        'en': 'Editing software', 'ar': 'برامج المونتاج',
        'skills': tuple((name, name) for name in (
            'Adobe Premiere Pro', 'After Effects', 'DaVinci Resolve', 'Final Cut Pro', 'CapCut',
            'Photoshop', 'Adobe Audition', 'Blender', 'Cinema 4D', 'Avid Media Composer',
        )),
    },
    {
        'key': 'craft',
        'en': 'What you do best', 'ar': 'ما تتقنه',
        'skills': (
            ('Color grading', 'تصحيح الألوان'),
            ('Motion graphics', 'موشن جرافيك'),
            ('Sound design', 'تصميم الصوت'),
            ('Storytelling', 'سرد القصص'),
            ('Reels & short-form', 'الريلز والفيديو القصير'),
            ('YouTube videos', 'فيديوهات يوتيوب'),
            ('Ads & commercials', 'الإعلانات'),
            ('Subtitles & captions', 'الترجمة والكابشن'),
            ('Visual effects (VFX)', 'المؤثرات البصرية (VFX)'),
            ('Thumbnail design', 'تصميم الصور المصغّرة'),
            ('Documentaries', 'الأفلام الوثائقية'),
            ('Weddings & events', 'الأفراح والمناسبات'),
        ),
    },
)

FIELD_ERRORS = {
    'fullname': ('Add your name.', 'اكتب اسمك.'),
    'title': ('Add your title, e.g. Video Editor.', 'اكتب مسمّاك الوظيفي، مثل: مونتير فيديو.'),
    'booking_url': (
        'Enter a full booking link (e.g. https://calendly.com/you) or a WhatsApp number.',
        'أدخل رابط حجز كاملًا (مثل https://calendly.com/you) أو رقم واتساب.',
    ),
    'picture': ('Upload a JPG, PNG or WebP photo under 5 MB.', 'ارفع صورة JPG أو PNG أو WebP أصغر من 5 ميجابايت.'),
    'thumbnail': (
        'That thumbnail is not a JPG, PNG or WebP image under 5 MB. Choose it again.',
        'هذه الصورة المصغّرة ليست JPG أو PNG أو WebP أصغر من 5 ميجابايت. اخترها مرة أخرى.',
    ),
    'skills': ('Pick at least one skill.', 'اختر مهارة واحدة على الأقل.'),
}


def _lang(arabic):
    return 'ar' if arabic else 'en'


def field_error(field, arabic=False):
    return FIELD_ERRORS[field][1 if arabic else 0]


# ---------------------------------------------------------------------------
# Switch and state
# ---------------------------------------------------------------------------

def enabled():
    row = SiteSettings.objects.only('launch_checklist_enabled').first()
    return row.launch_checklist_enabled if row else True  # mirrors the field default


def _account(user):
    return getattr(user, 'user_account', None)  # RelatedObjectDoesNotExist is an AttributeError


def _editor_account(user):
    account = _account(user)
    return account if account is not None and account.account_type == 'editor' else None


def start(user):
    """Put a brand-new editor into the launch flow. Called at signup; never raises."""
    try:
        account = _editor_account(user)
        if account is None or not enabled():
            return False
        account.launch_status = 'active'
        account.save(update_fields=['launch_status', 'updated_at'])
        return True
    except Exception:
        logger.exception('Could not start the launch checklist for user %s', getattr(user, 'pk', None))
        return False


SKIP_MINUTES = 30


def skip_now(request):
    """"Skip for now": the checklist stays out of the way for a short while, then returns."""
    import time
    request.session['launch_skipped_at'] = time.time()


def skipped(request):
    import time
    at = request.session.get('launch_skipped_at')
    return bool(at) and time.time() - at < SKIP_MINUTES * 60


def is_active(user):
    """Every editor who hasn't reached 100 XP: the site sends them to the checklist.

    That includes accounts made before the checklist existed (empty status): they are
    brought into it on first sight, keeping credit for a theme they already chose, and
    marked done straight away if their portfolio already earns the full 100 XP.
    """
    account = _editor_account(user)
    if account is None or not enabled() or account.launch_status == 'done':
        return False
    if account.launch_status == '':
        profile = Profile.objects.filter(user=user).only('theme').first()
        if profile and profile.theme_id:
            account.launch_theme_picked = True
        account.launch_status = 'active'
        account.save(update_fields=['launch_status', 'launch_theme_picked', 'updated_at'])
    if all(step_status(user)[key] for key in STEPS):
        finish(user)
        return False
    return True


def in_flow(user):
    """Any editor: the launch pages are open to them (finished ones see their 100 XP screen)."""
    return _editor_account(user) is not None and enabled()


def mark_theme_picked(user):
    """Remember that the user chose a theme. Returns whether they already had."""
    account = _editor_account(user)
    if account is None:
        return False
    if account.launch_theme_picked:
        return True
    account.launch_theme_picked = True
    account.save(update_fields=['launch_theme_picked', 'updated_at'])
    return False


def finish(user):
    account = _editor_account(user)
    if account is None or account.launch_status != 'active':
        return
    account.launch_status = 'done'
    account.save(update_fields=['launch_status', 'updated_at'])
    activation.track(user, 'launch_finished', seconds_since_signup=activation.seconds_since_signup(user))


def step_status(user):
    """{step: done} for every step, derived from the portfolio itself.

    Also ``publish`` (paid and public): not a step, but it changes what the end screens say.
    """
    info = PersonalInfo.objects.filter(user=user).only('full_name', 'title').first()
    account = _account(user)
    profile = Profile.objects.filter(user=user).only('is_public').first()
    payment = UserPayment.objects.filter(user=user, status='paid').select_related('subscription').last()
    return {
        'personal': bool(info and (info.full_name or '').strip() and (info.title or '').strip()),
        'project': Project.objects.filter(user=user).exists(),
        'theme': bool(account and account.launch_theme_picked),
        'skills': Skill.objects.filter(user=user).exists(),
        'publish': bool(payment and payment.is_active and profile and profile.is_public),
    }


def needs_photo(user):
    """The chosen theme shows a profile photo and there is none yet."""
    from core.onboarding import PICTURE_REQUIRED_THEMES
    profile = Profile.objects.filter(user=user).select_related('theme').first()
    return bool(profile and profile.theme and profile.theme.name.lower() in PICTURE_REQUIRED_THEMES
                and not profile.picture)


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

STEP_URL_NAMES = {
    'personal': 'launch_personal',
    'project': 'launch_project',
    'theme': 'themes',
    'skills': 'launch_skills',
}


def step_url(key, arabic=False):
    name = STEP_URL_NAMES[key]
    return reverse(f'arabic_{name}' if arabic else name)


def checklist_url(arabic=False, done=None):
    url = reverse('arabic_launch' if arabic else 'launch')
    return f'{url}?done={done}' if done else url


def launched_url(user, arabic=False):
    url = reverse('preview', kwargs={'username': user.username}) + '?launched=1'
    return url + '&lang=ar' if arabic else url


def complete_step(user, key, arabic=False, was_done=False):
    """Record a saved step and return where to go next: back to the checklist,
    celebrating the step (and its XP) if it is newly done. Reaching 100 XP finishes the flow.
    """
    if not was_done:
        activation.track(user, 'launch_step_completed', step=key, xp=XP[key],
                         seconds_since_signup=activation.seconds_since_signup(user))
    status = step_status(user)
    if is_active(user) and all(status[k] for k in STEPS):
        finish(user)
    return checklist_url(arabic, done=None if was_done else key)


# ---------------------------------------------------------------------------
# What the checklist shows
# ---------------------------------------------------------------------------

def progress(user, arabic=False):
    lang = _lang(arabic)
    done = step_status(user)
    current = next((key for key in STEPS if not done[key]), None)
    steps = []
    for number, key in enumerate(STEPS, 1):
        copy = STEP_COPY[key]
        steps.append({
            'key': key,
            'number': number,
            'icon': copy['icon'],
            'tint': STEP_TINTS[key],
            'xp': XP[key],
            'done': done[key],
            'current': key == current,
            'locked': not done[key] and key != current,
            'url': step_url(key, arabic),
            **copy[lang],
        })
    xp = earned_xp(done)
    return {
        'steps': steps,
        'done': done,
        'current': current,
        'done_count': sum(1 for key in STEPS if done[key]),
        'total': len(STEPS),
        'xp': xp,
        'xp_total': XP_TOTAL,
        'percent': percent(xp),
        'ready': xp >= XP_TOTAL,
        'is_live': done['publish'],
        'photo_hint': done['theme'] and needs_photo(user),
    }


def earned_xp(status):
    return sum(XP[key] for key in STEPS if status[key])


def percent(xp):
    return round(100 * xp / XP_TOTAL)


def step_header(key, arabic=False, user=None):
    """Context for a step page: "Step n of 4", the XP it is worth, and (given ``user``)
    the XP earned so far and whether saving it reaches 100 XP."""
    number = STEPS.index(key) + 1
    xp_so_far = sum(XP[k] for k in STEPS[:number - 1])
    finishes = False
    if user is not None:
        status = step_status(user)
        xp_so_far = earned_xp(status)
        finishes = all(status[k] for k in STEPS if k != key)
    return {
        'key': key,
        'number': number,
        'total': len(STEPS),
        'xp': XP[key],
        'xp_so_far': xp_so_far,
        'xp_total': XP_TOTAL,
        'percent': percent(xp_so_far),
        'tint': STEP_TINTS[key],
        'icon': STEP_COPY[key]['icon'],
        'back_url': checklist_url(arabic),
        'finishes': finishes,
        **STEP_COPY[key][_lang(arabic)],
    }


# ---------------------------------------------------------------------------
# A thumbnail the user chose for a video
# ---------------------------------------------------------------------------

THUMB_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}
THUMB_FIELD = re.compile(r'thumbnail_(\d+)')


def clean_thumbnail(upload):
    """The upload as a safely named ContentFile, or None if it isn't a usable image.

    The format is read from the bytes (Pillow), never from the file name or the
    browser's content type, and the stored name is generated.
    """
    if not upload or not upload.size or upload.size > MAX_PHOTO_BYTES:
        return None
    data = upload.read()
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            image.verify()
    except Exception:
        return None
    ext = THUMB_FORMATS.get(fmt)
    return ContentFile(data, name=f'thumb_{uuid4().hex[:12]}.{ext}') if ext else None


def posted_thumbnails(files, limit):
    """``(thumbnails, bad_rows)`` from fields named ``thumbnail_<row>``: {row: file} and the rows whose file was refused."""
    thumbnails, bad = {}, set()
    for field, upload in files.items():
        match = THUMB_FIELD.fullmatch(field)
        if not match or int(match.group(1)) >= limit:
            continue
        row = int(match.group(1))
        thumb = clean_thumbnail(upload)
        if thumb:
            thumbnails[row] = thumb
        else:
            bad.add(row)
    return thumbnails, bad


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def clean_skill_names(raw_names):
    """Trim, collapse spaces, drop blanks and case-insensitive duplicates, cap the count."""
    names, seen = [], set()
    for raw in raw_names:
        name = re.sub(r'\s+', ' ', str(raw or '')).strip()[:MAX_SKILL_LENGTH].strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append(name)
        if len(names) >= MAX_SKILLS:
            break
    return names


def save_skills(user, names):
    """Make the user's skills exactly ``names``, keeping rows that stay (and their order)."""
    wanted = {name.casefold(): name for name in names}
    kept = set()
    for skill in Skill.objects.filter(user=user):
        key = skill.name.strip().casefold()
        if key in wanted and key not in kept:
            kept.add(key)
        else:
            skill.delete()
    Skill.objects.bulk_create([
        Skill(user=user, name=name) for key, name in wanted.items() if key not in kept
    ])


def skill_groups(selected, arabic=False):
    """Preset chips per group plus the user's own extras, with ``checked`` flags."""
    lang = _lang(arabic)
    chosen = {name.casefold() for name in selected}
    preset_keys = set()
    groups = []
    for group in SKILL_GROUPS:
        chips = []
        for en, ar in group['skills']:
            preset_keys.update({en.casefold(), ar.casefold()})
            label = ar if arabic else en
            # A skill saved in the other language still counts as picked.
            checked = en.casefold() in chosen or ar.casefold() in chosen
            value = next((n for n in selected if n.casefold() in (en.casefold(), ar.casefold())), label)
            chips.append({'value': value, 'label': label, 'checked': checked})
        groups.append({'key': group['key'], 'title': group[lang], 'chips': chips})
    extras = [{'value': n, 'label': n, 'checked': True} for n in selected if n.casefold() not in preset_keys]
    return groups, extras
