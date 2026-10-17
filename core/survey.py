"""
"How did you hear about Skillifly?": a one-question Arabic page worth bonus XP.

Reached from the manage hub (which also shows the answer counts). One answer per user;
answering again is a no-op, so the XP can only be earned once.
"""
from django.db import IntegrityError, transaction
from django.db.models import Count

from core.models import HeardAboutResponse

XP = 25
MAX_DETAIL = 120

# (key, Arabic label, lucide icon, tint, asks for a short detail?)
OPTIONS = (
    ('instagram', 'إنستجرام', 'instagram', 'fuchsia', True),
    ('tiktok', 'تيك توك', 'music-2', 'slate', False),
    ('youtube', 'يوتيوب', 'youtube', 'amber', False),
    ('facebook', 'فيسبوك', 'facebook', 'blue', False),
    ('friend', 'صديق أو زميل', 'users', 'emerald', True),
    ('google', 'بحث جوجل', 'search', 'sky', False),
    ('other', 'مكان آخر', 'sparkles', 'violet', True),
)
KEYS = {key for key, *_ in OPTIONS}
LABELS = {key: label for key, label, *_ in OPTIONS}
DETAIL_KEYS = {key for key, _, _, _, ask in OPTIONS if ask}

# Follow-up question shown for options that ask for detail: (label, placeholder). Default is the generic one.
DETAIL_PROMPTS = {
    'instagram': ('من هو صانع المحتوى الذي عرفت منه Skillifly؟', 'مثال: اسم الحساب @username'),
}
DEFAULT_PROMPT = ('تفاصيل', 'مثال: اسم الصديق أو الموقع')


def options():
    return [{'key': k, 'label': label, 'icon': icon, 'tint': tint, 'ask': ask,
             'prompt': DETAIL_PROMPTS.get(k, DEFAULT_PROMPT)[0], 'placeholder': DETAIL_PROMPTS.get(k, DEFAULT_PROMPT)[1]}
            for k, label, icon, tint, ask in OPTIONS]


def existing(user):
    return HeardAboutResponse.objects.filter(user=user).first()


def save(user, source, detail=''):
    """Record the answer and award the XP. Returns ``(response, newly_awarded)``, or ``(None, False)`` for a bad answer."""
    if source not in KEYS:
        return None, False
    detail = ' '.join((detail or '').split())[:MAX_DETAIL] if source in DETAIL_KEYS else ''
    try:
        with transaction.atomic():
            response = HeardAboutResponse.objects.create(user=user, source=source, detail=detail, xp_awarded=XP)
    except IntegrityError:  # double submit / second tab: keep the first answer, award nothing more
        return existing(user), False
    return response, True


def summary():
    """Answer counts, biggest first, for the manage hub."""
    counts = dict(HeardAboutResponse.objects.values_list('source').annotate(n=Count('id')))
    total = sum(counts.values())
    rows = [{'key': key, 'label': LABELS[key], 'count': n, 'percent': round(100 * n / total)}
            for key, n in sorted(((k, counts.get(k, 0)) for k in LABELS), key=lambda kv: -kv[1]) if n]
    return {'total': total, 'rows': rows}
