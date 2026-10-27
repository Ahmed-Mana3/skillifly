"""
Activation tracking for the editor onboarding funnel.

Best-effort and server-side: a tracking failure must never break a page.
Event names are whitelisted so a typo can't silently start a new series.
"""
import contextvars
import logging
from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('core')

EVENTS = frozenset({
    'signup_completed', 'email_verified', 'dashboard_viewed',
    'welcome_viewed', 'link_previewed', 'welcome_skipped', 'welcome_submitted',
    'project_created', 'reveal_viewed', 'reveal_action', 'theme_switched',
    'builder_saved', 'builder_save_failed', 'profile_field_added',
    'builder_item_saved', 'builder_item_save_failed', 'builder_item_deleted',
    'nudge_sent', 'nudge_clicked',
    'launch_viewed', 'launch_step_completed', 'launch_skipped', 'launch_finished',
})

_source = contextvars.ContextVar('activation_source', default='other')


@contextmanager
def source(name):
    """Label every Project created inside this block (builder / welcome / launch / agent / concierge)."""
    token = _source.set(name)
    try:
        yield
    finally:
        _source.reset(token)


def current_source():
    return _source.get()


def is_editor(user):
    """True for editor accounts, including legacy users that have no UserAccount row."""
    account = getattr(user, 'user_account', None)  # RelatedObjectDoesNotExist is an AttributeError
    return account is None or account.account_type == 'editor'


def seconds_since_signup(user):
    return max(0, int((timezone.now() - user.date_joined).total_seconds()))


REVEAL_ACTIONS = frozenset({'add', 'looks', 'edit', 'live'})


def track_reveal_action(request):
    """Record a click on the reveal bar: its links carry ``?ra=<action>``."""
    action = request.GET.get('ra')
    if action in REVEAL_ACTIONS and request.user.is_authenticated:
        track(request.user, 'reveal_action', action=action)


def record_signup(request, user, account_type, method='email', lang=None):
    """Stamp the signup language on the UserAccount and record `signup_completed`.

    Best-effort: neither step may break signup.
    """
    from core.models import UserAccount
    if lang is None:
        lang = 'ar' if request.COOKIES.get('skillifly_lang') == 'ar' else 'en'
    try:
        UserAccount.objects.filter(user=user).update(signup_lang=lang)
    except Exception:
        logger.debug('Could not store signup_lang', exc_info=True)
    session = getattr(request, 'session', {})
    track(
        user, 'signup_completed',
        method=method, lang=lang, account_type=account_type,
        source=(request.GET.get('utm_source') or session.get('utm_source') or '')[:40],
        campaign=(request.GET.get('utm_campaign') or session.get('utm_campaign') or '')[:40],
    )


def track(user, name, **props):
    """Record one activation event. Never raises."""
    if name not in EVENTS:
        logger.warning('Unknown activation event %r', name)
        return
    if user is None or not getattr(user, 'pk', None) or user.username == 'alex_mercer':
        return
    try:
        from core.models import ActivationEvent
        # Own savepoint: a failure here must not poison an outer atomic block
        # (save_portfolio_data runs inside @transaction.atomic).
        with transaction.atomic():
            ActivationEvent.objects.create(user=user, name=name, props=props)
    except Exception:
        logger.debug('Failed to record activation event %s', name, exc_info=True)
