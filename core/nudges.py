"""
Onboarding nudge emails: rules, copy and rendering.

The scheduling (who is due what, when) lives here so it can be unit-tested; the
``send_onboarding_nudges`` management command is a thin runner around it.
"""
import datetime
import logging

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from core import activation
from core.models import CustomUser, NudgeLog, Project, UserPayment

logger = logging.getLogger('core')

HOUR = datetime.timedelta(hours=1)
DAY = datetime.timedelta(days=1)

QUIET_START, QUIET_END = 22, 9  # Cairo local time: no emails from 22:00 until 09:00

# (key, min_age, max_age, matches(project_count, has_paid)) in priority order.
# A rule applies while min_age <= account age < max_age. The "no project" windows are
# contiguous so a delayed run (quiet hours, downtime) can't skip a user between two nudges.
RULES = (
    ('no_project_1h', 1 * HOUR, 24 * HOUR, lambda n, paid: n == 0),
    ('no_project_24h', 24 * HOUR, 72 * HOUR, lambda n, paid: n == 0),
    ('no_project_72h', 72 * HOUR, 6 * DAY, lambda n, paid: n == 0),
    ('no_project_7d', 7 * DAY, 8 * DAY, lambda n, paid: n == 0),
    ('few_projects_48h', 48 * HOUR, 6 * DAY, lambda n, paid: 1 <= n <= 2),
    ('ready_unpaid_3d', 3 * DAY, 10 * DAY, lambda n, paid: n >= 3 and not paid),
)
KEYS = tuple(rule[0] for rule in RULES)
LOOKBACK = 11 * DAY  # a bit more than the longest rule window

# Per-key copy. `path` is appended to SITE_BASE_URL; `cta` None = plain email, reply expected.
COPY = {
    'no_project_1h': {
        'path': '/welcome/', 'ar_path': '/ar/welcome/',
        'en': {
            'subject': 'Your portfolio is 60 seconds away',
            'heading': 'Hi {name}, one link and your portfolio is on its way',
            'body': "You've signed up, but your portfolio is still empty. Paste one video link and we'll build the portfolio around it: title, thumbnail and all.",
            'cta': 'Add my first video',
        },
        'ar': {
            'subject': 'معرض أعمالك على بُعد دقيقة واحدة',
            'heading': 'أهلًا {name}، رابط واحد ويبدأ معرض أعمالك',
            'body': 'سجّلت في Skillifly لكن معرضك ما زال فارغًا. الصق رابط فيديو واحدًا وسنبني المعرض حوله: العنوان والصورة المصغّرة وكل شيء.',
            'cta': 'أضف أول فيديو لي',
        },
    },
    'no_project_24h': {
        'path': '/welcome/', 'ar_path': '/ar/welcome/',
        'extra_path': '/examples/', 'ar_extra_path': '/ar/examples/',
        'en': {
            'subject': 'See what other editors built',
            'heading': 'Hi {name}, here is what a finished portfolio looks like',
            'body': 'Editors on Skillifly show their best work in one shareable link. Browse the live examples, then add your first video. It takes under a minute.',
            'cta': 'Add my first video',
            'extra_cta': 'See live examples',
        },
        'ar': {
            'subject': 'شاهد ما صنعه مونتيرون آخرون',
            'heading': 'أهلًا {name}، هكذا يبدو المعرض المكتمل',
            'body': 'يعرض المونتيرون على Skillifly أفضل أعمالهم في رابط واحد قابل للمشاركة. تصفّح الأمثلة الحيّة ثم أضف أول فيديو لك. يستغرق أقل من دقيقة.',
            'cta': 'أضف أول فيديو لي',
            'extra_cta': 'شاهد الأمثلة الحيّة',
        },
    },
    'no_project_72h': {
        'path': None, 'ar_path': None,
        'en': {
            'subject': 'Quick question',
            'heading': 'Hi {name},',
            'body': "{founder_en} You signed up a few days ago but haven't added a video yet. What got in the way? Just hit reply; one line is plenty. If it's easier, send me your video links and I'll set the portfolio up for you.",
            'cta': None,
        },
        'ar': {
            'subject': 'سؤال سريع',
            'heading': 'أهلًا {name}،',
            'body': '{founder_ar} سجّلت منذ أيام لكنك لم تضف فيديو بعد. ما الذي أعاقك؟ ردّ على هذه الرسالة بسطر واحد فقط. وإن كان أسهل، أرسل لي روابط فيديوهاتك وسأجهّز لك المعرض.',
            'cta': None,
        },
    },
    'no_project_7d': {
        'path': '/welcome/', 'ar_path': '/ar/welcome/',
        'en': {
            'subject': 'Last note from Skillifly',
            'heading': 'Hi {name}, we will stop reminding you after this',
            'body': 'Your account stays exactly as it is. Whenever you have a video link ready, your portfolio takes under a minute to build.',
            'cta': 'Add a video',
        },
        'ar': {
            'subject': 'رسالة أخيرة من Skillifly',
            'heading': 'أهلًا {name}، لن نرسل لك تذكيرات بعد هذه الرسالة',
            'body': 'حسابك سيبقى كما هو. متى جهّزت رابط فيديو، يستغرق بناء معرضك أقل من دقيقة.',
            'cta': 'أضف فيديو',
        },
    },
    'few_projects_48h': {
        'path': '/welcome/?add=1', 'ar_path': '/ar/welcome/?add=1',
        'en': {
            'subject': 'Add 2 more videos to make it client-ready',
            'heading': 'Hi {name}, your portfolio has a great start',
            'body': 'Clients usually decide after seeing 3 to 6 strong pieces. You have {projects} so far. Add a couple more to make it client-ready.',
            'cta': 'Add more videos',
        },
        'ar': {
            'subject': 'أضف فيديوهين ليصبح معرضك جاهزًا للعملاء',
            'heading': 'أهلًا {name}، بداية معرضك ممتازة',
            'body': 'يقرّر العملاء عادةً بعد مشاهدة 3 إلى 6 أعمال قوية. لديك حاليًا {projects}. أضف فيديوهين آخرين ليصبح معرضك جاهزًا للعملاء.',
            'cta': 'أضف فيديوهات أخرى',
        },
    },
    'ready_unpaid_3d': {
        'path': '/payment/', 'ar_path': '/ar/payment/',
        'en': {
            'subject': 'Your portfolio is ready to go live',
            'heading': 'Hi {name}, your portfolio is ready',
            'body': 'You have {projects} in your portfolio. Go live so clients can see it at {site}/{username}.',
            'cta': 'Go live',
        },
        'ar': {
            'subject': 'معرض أعمالك جاهز للنشر',
            'heading': 'أهلًا {name}، معرضك جاهز',
            'body': 'لديك {projects} في معرضك. انشره ليراه العملاء على {site}/{username}.',
            'cta': 'انشر معرضك',
        },
    },
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def cairo_hour(now=None):
    """Hour of day (0-23) in Cairo, falling back to a fixed UTC+2 if tz data is missing."""
    now = now or timezone.now()
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo('Africa/Cairo')).hour
    except Exception:
        return (now.astimezone(datetime.timezone.utc) + datetime.timedelta(hours=2)).hour


def in_quiet_hours(now=None):
    hour = cairo_hour(now)
    return hour >= QUIET_START or hour < QUIET_END


# ---------------------------------------------------------------------------
# Eligibility and rule selection
# ---------------------------------------------------------------------------

def eligible_users(now=None):
    """Active editors who recently joined and haven't opted out."""
    now = now or timezone.now()
    qs = (
        CustomUser.objects
        .filter(is_active=True, date_joined__gte=now - LOOKBACK)
        .exclude(is_superuser=True)
        .exclude(username='alex_mercer')
        .exclude(user_account__account_type__in=['client', 'school_admin'])
        .exclude(user_account__email_opt_out=True)
        .select_related('user_account')
    )
    return qs


def due_key(user, now=None, project_count=None, has_paid=None):
    """The first nudge key this user is due and hasn't received, or None."""
    now = now or timezone.now()
    age = now - user.date_joined
    n = Project.objects.filter(user=user).count() if project_count is None else project_count
    paid = (
        UserPayment.objects.filter(user=user, status='paid').exists()
        if has_paid is None else has_paid
    )
    already = set(NudgeLog.objects.filter(user=user).values_list('key', flat=True))
    for key, min_age, max_age, matches in RULES:
        if key in already:
            continue
        if min_age <= age < max_age and matches(n, paid):
            return key
    return None


# ---------------------------------------------------------------------------
# Rendering and sending
# ---------------------------------------------------------------------------

def unsubscribe_url(user):
    token = signing.dumps(user.pk, salt='nudge-unsub')
    return f'{settings.SITE_BASE_URL}/email/unsubscribe/{token}/'


def _projects_phrase(n, ar):
    if ar:
        return {1: 'فيديو واحد', 2: 'فيديوهان'}.get(n, f'{n} فيديوهات')
    return f'{n} video' + ('' if n == 1 else 's')


def _link(path, key):
    sep = '&' if '?' in path else '?'
    return f'{settings.SITE_BASE_URL}{path}{sep}utm_source=nudge&utm_campaign={key}'


def build_block(user, key, lang, project_count):
    """One language's content for the email template."""
    copy = COPY[key]
    ar = lang == 'ar'
    c = copy[lang]
    founder = getattr(settings, 'NUDGE_FOUNDER_NAME', '').strip()
    fmt = {
        'name': user.first_name or user.username,
        'projects': _projects_phrase(project_count, ar),
        'username': user.username,
        'site': settings.SITE_BASE_URL.replace('https://', '').replace('http://', ''),
        'founder_en': f"I'm {founder}, I built Skillifly." if founder else 'We built Skillifly.',
        'founder_ar': f'أنا {founder}، مؤسس Skillifly.' if founder else 'نحن فريق Skillifly.',
    }
    path = copy['ar_path'] if ar else copy['path']
    extra_path = copy.get('ar_extra_path') if ar else copy.get('extra_path')
    return {
        'lang': lang,
        'dir': 'rtl' if ar else 'ltr',
        'subject': c['subject'],
        'heading': c['heading'].format(**fmt),
        'body': c['body'].format(**fmt),
        'cta_label': c.get('cta'),
        'cta_url': _link(path, key) if path and c.get('cta') else '',
        'extra_label': c.get('extra_cta'),
        'extra_url': _link(extra_path, key) if extra_path and c.get('extra_cta') else '',
    }


def render_nudge(user, key, project_count=0):
    """Returns (subject, text_body, html_body) for ``user``'s language preference."""
    account = getattr(user, 'user_account', None)
    lang = (account.signup_lang if account else '') or ''
    langs = [lang] if lang in ('ar', 'en') else ['ar', 'en']  # unknown: Arabic first, then English
    blocks = [build_block(user, key, code, project_count) for code in langs]
    subject = ' · '.join(b['subject'] for b in blocks)
    context = {'blocks': blocks, 'unsubscribe_url': unsubscribe_url(user), 'site_url': settings.SITE_BASE_URL}
    return (
        subject,
        render_to_string('emails/nudge.txt', context),
        render_to_string('emails/nudge.html', context),
    )


def send_nudge(user, key, project_count=0):
    """Send one nudge. Returns True if it went out. Each (user, key) is sent at most once.

    The log row is written first (unique constraint = no double send, even with
    two overlapping runs) and removed again if the send fails, so the next run retries.
    """
    try:
        with transaction.atomic():
            log = NudgeLog.objects.create(user=user, key=key)
    except IntegrityError:
        return False

    try:
        subject, text, html = render_nudge(user, key, project_count)
        message = EmailMultiAlternatives(
            subject=subject, body=text,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@skillifly.cloud'),
            to=[user.email],
            headers={'List-Unsubscribe': f'<{unsubscribe_url(user)}>'},
        )
        message.attach_alternative(html, 'text/html')
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Nudge %s to user %s failed', key, user.pk)
        log.delete()
        return False

    activation.track(user, 'nudge_sent', key=key)
    return True
