"""add_concierge_projects, the report's source breakdown, and the Arabic signup help text."""
import io
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from core import activation
from core.models import ActivationEvent, PersonalInfo, Profile, Project
from core.oembed import VideoMeta
from core.testing_helpers import clear_cache, make_editor, seed_themes, site_settings


def lookup(url):
    if 'private' in url:
        return VideoMeta(url=url, provider='youtube', ok=False, error='private')
    provider = 'vimeo' if 'vimeo' in url else 'youtube'
    return VideoMeta(url=url, provider=provider, title=f'Title of {url[-4:]}', video_type='long')


class ConciergeCommandTests(TestCase):
    def setUp(self):
        clear_cache()
        self.themes = seed_themes()
        site_settings()
        self.user = make_editor()
        for target, kwargs in (
            ('core.oembed.fetch', dict(side_effect=lookup)),
            ('core.oembed.download_thumbnail', dict(return_value=None)),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cmd(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command('add_concierge_projects', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_adds_projects_labelled_as_concierge_and_sets_up_the_portfolio(self):
        out, _ = self.run_cmd('sara', 'https://youtu.be/aaaa1111', 'https://vimeo.com/2222')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 2)
        self.assertIn('Done: 2 added to sara (source=concierge)', out)
        sources = set(ActivationEvent.objects.filter(name='project_created').values_list('props__source', flat=True))
        self.assertEqual(sources, {'concierge'})
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.full_name, info.title), ('Sara Ali', 'Video Editor'))

    def test_not_limited_to_the_welcome_pages_three_links(self):
        urls = [f'https://vimeo.com/{1000 + i}' for i in range(7)]
        self.run_cmd('sara', *urls)
        self.assertEqual(Project.objects.filter(user=self.user).count(), 7)

    def test_titles_apply_in_order_and_the_rest_come_from_the_lookup(self):
        self.run_cmd('sara', 'https://vimeo.com/1111', 'https://vimeo.com/2222', '--title', 'Brand film')
        titles = list(Project.objects.filter(user=self.user).order_by('id').values_list('title', flat=True))
        self.assertEqual(titles, ['Brand film', 'Title of 2222'])

    def test_arabic_defaults(self):
        self.run_cmd('sara', 'https://vimeo.com/3333', '--lang', 'ar')
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'مونتير فيديو')

    def test_refused_and_duplicate_links_are_reported(self):
        Project.objects.create(user=self.user, title='Old', url='https://vimeo.com/4444')
        out, _ = self.run_cmd('sara', 'https://youtube.com/watch?v=private1', 'https://vimeo.com/4444',
                              'https://vimeo.com/5555')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 2)
        self.assertIn('skipped https://youtube.com/watch?v=private1', out)
        self.assertIn('private', out)
        self.assertIn('already in the portfolio', out)
        self.assertIn('Done: 1 added', out)

    def test_dry_run_creates_nothing(self):
        out, _ = self.run_cmd('sara', 'https://vimeo.com/6666', 'https://youtube.com/watch?v=private2', '--dry-run')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 0)
        self.assertFalse(PersonalInfo.objects.filter(user=self.user).exists())
        self.assertIn('would be refused', out)
        self.assertIn('Dry run: nothing created.', out)

    def test_refuses_unknown_inactive_and_non_editor_users(self):
        make_editor('pending', is_active=False)
        make_editor('buyer', account_type='client')
        for name, message in (('nobody', 'No user named'), ('pending', 'verified'), ('buyer', 'not an editor')):
            with self.assertRaisesMessage(CommandError, message):
                call_command('add_concierge_projects', name, 'https://vimeo.com/1')

    def test_does_not_overwrite_an_existing_theme_or_personal_info(self):
        Profile.objects.create(user=self.user, theme=self.themes['Pro'])
        PersonalInfo.objects.create(user=self.user, full_name='S', title='Colorist', email='', phone='', bio='')
        self.run_cmd('sara', 'https://vimeo.com/7777')
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Pro'])
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'Colorist')


class ReportSourceBreakdownTests(TestCase):
    def test_first_project_by_source_and_concierge_note(self):
        site_settings()
        a, b, c = make_editor('a'), make_editor('b'), make_editor('c')
        for user, sources in ((a, ['welcome', 'builder']), (b, ['concierge']), (c, ['builder'])):
            for source in sources:
                ActivationEvent.objects.create(
                    user=user, name='project_created', props={'source': source, 'seconds_since_signup': 60},
                )
        out = io.StringIO()
        call_command('activation_report', '--since', '2020-01-01', stdout=out)
        text = out.getvalue()
        self.assertIn('first project by source', text)
        # Only each user's FIRST project counts: a=welcome, b=concierge, c=builder.
        self.assertIn('builder=1, concierge=1, welcome=1', text)
        self.assertIn('concierge = set up by hand', text)

    def test_no_note_without_concierge(self):
        site_settings()
        user = make_editor('a')
        ActivationEvent.objects.create(user=user, name='project_created', props={'source': 'welcome'})
        out = io.StringIO()
        call_command('activation_report', '--since', '2020-01-01', stdout=out)
        self.assertIn('welcome=1', out.getvalue())
        self.assertNotIn('concierge', out.getvalue())


class ArabicSignupHelpTextTests(TestCase):
    def test_help_text_is_localised(self):
        site_settings()
        resp = self.client.get(reverse('arabic_signup'))
        self.assertContains(resp, 'هذا هو الرابط الذي ستشاركه مع العملاء')
        self.assertNotContains(resp, "the link you'll share")
        # (a fresh client: visiting /ar/ stored the Arabic language cookie on the first one)
        from django.test import Client
        self.assertContains(Client().get(reverse('signup')),
                            "This is the link you'll share with clients")
