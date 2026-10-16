"""Shared fixtures for the onboarding-v2 test modules (not itself a test module)."""
import io
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from core.models import (
    Category, Profile, SiteSettings, Subscription, Theme, UserAccount, UserPayment,
)

User = get_user_model()


def seed_themes():
    """Video Editor themes used by onboarding (Creative, Pro, Minimal, Animated)."""
    category, _ = Category.objects.get_or_create(name='Video Editor')
    themes = {}
    for name in ('Creative', 'Pro', 'Minimal', 'Animated'):
        themes[name], _ = Theme.objects.get_or_create(category=category, name=name)
    return themes


def site_settings(**flags):
    row = SiteSettings.objects.first() or SiteSettings.objects.create()
    for key, value in flags.items():
        setattr(row, key, value)
    row.save()
    return row


def make_editor(username='sara', first_name='Sara', last_name='Ali', account_type='editor',
                days_old=0, hours_old=0, **extra):
    # password=None -> unusable password: no PBKDF2 hashing, which dominates test time.
    # Tests sign in with client.force_login().
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password=None,
        first_name=first_name, last_name=last_name, **extra,
    )
    if account_type is not None:
        # Finished with the launch checklist by default, so tests about other things reach the dashboard.
        # Launch tests set launch_status themselves.
        UserAccount.objects.create(user=user, account_type=account_type, launch_status='done')
    if days_old or hours_old:
        User.objects.filter(pk=user.pk).update(
            date_joined=timezone.now() - timedelta(days=days_old, hours=hours_old),
        )
        user.refresh_from_db()
    return user


def give_payment(user, days_ago=0, plan_days=30):
    sub, _ = Subscription.objects.get_or_create(name=f'Plan{plan_days}', duration=1, days=plan_days)
    payment = UserPayment.objects.create(user=user, subscription=sub, amount=99, status='paid')
    if days_ago:
        UserPayment.objects.filter(pk=payment.pk).update(date=timezone.now() - timedelta(days=days_ago))
    return payment


def png_bytes(width=320, height=180, fmt='PNG'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def builder_post(project_rows=(), fullname='Sara Ali', title='Video Editor', **personal):
    """POST body for the builder / update_portfolio formsets."""
    post = {'fullname': fullname, 'title': title}
    post.update(personal)
    for prefix, rows in [
        ('skills', []), ('education', []), ('experience', []),
        ('projects', list(project_rows)), ('links', []), ('creators', []),
        ('project_categories', []),
    ]:
        post[f'{prefix}-TOTAL_FORMS'] = str(len(rows))
        post[f'{prefix}-INITIAL_FORMS'] = '0'
        post[f'{prefix}-MIN_NUM_FORMS'] = '0'
        post[f'{prefix}-MAX_NUM_FORMS'] = '1000'
        for i, row in enumerate(rows):
            for key, value in row.items():
                post[f'{prefix}-{i}-{key}'] = value
    return post


def project_row(name, url='https://www.youtube.com/watch?v=dQw4w9WgXcQ', video_type='long'):
    return {'id': '', 'name': name, 'url': url, 'description': '', 'video_type': video_type, 'category_id': ''}


class FakeResp:
    """Just enough of ``requests.Response`` for core.oembed."""

    def __init__(self, status=200, json_data=None, headers=None, content=b''):
        self.status_code = status
        self._json = json_data
        self.headers = headers or {}
        self._content = content
        self.is_redirect = status in (301, 302, 303, 307, 308)

    def json(self):
        if self._json is None:
            raise ValueError('no json body')
        return self._json

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TempMediaMixin:
    """Point MEDIA_ROOT at a throwaway directory so tests never write to ./media."""

    @classmethod
    def setUpClass(cls):
        from django.test.utils import override_settings
        cls._media_dir = tempfile.mkdtemp(prefix='skillifly-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)


def clear_cache():
    cache.clear()
