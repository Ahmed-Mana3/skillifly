"""PR-1: activation tracking, project signal, signup events and the funnel report."""
import csv
import io
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import activation
from core.management.commands.activation_report import prob_better, wilson_interval
from core.models import ActivationEvent, EmailOTP, PersonalInfo, Project, UserAccount, CustomUser
from core.testing_helpers import (
    builder_post, give_payment, make_editor, project_row, seed_themes, site_settings,
)


def events(name=None, user=None):
    qs = ActivationEvent.objects.all()
    if name:
        qs = qs.filter(name=name)
    if user:
        qs = qs.filter(user=user)
    return qs


class TrackTests(TestCase):
    def setUp(self):
        self.user = make_editor()

    def test_records_a_whitelisted_event(self):
        activation.track(self.user, 'welcome_viewed', entry='dashboard')
        event = events('welcome_viewed').get()
        self.assertEqual((event.user, event.props), (self.user, {'entry': 'dashboard'}))

    def test_unknown_event_names_are_ignored(self):
        with self.assertLogs('core', level='WARNING'):
            activation.track(self.user, 'wellcome_viewed')
        self.assertEqual(ActivationEvent.objects.count(), 0)

    def test_demo_user_and_anonymous_are_ignored(self):
        demo = make_editor(username='alex_mercer')
        activation.track(demo, 'welcome_viewed')
        activation.track(None, 'welcome_viewed')
        self.assertEqual(ActivationEvent.objects.count(), 0)

    def test_never_raises_when_the_write_fails(self):
        with patch.object(ActivationEvent.objects, 'create', side_effect=RuntimeError('db down')):
            activation.track(self.user, 'welcome_viewed')  # must not raise

    def test_failed_write_does_not_poison_the_outer_transaction(self):
        with transaction.atomic():
            other = make_editor(username='inside_atomic')
            with patch.object(ActivationEvent.objects, 'create', side_effect=IntegrityError('boom')):
                activation.track(other, 'welcome_viewed')
            # The outer atomic block is still usable: this would raise
            # TransactionManagementError if the failure had broken it.
            self.assertTrue(CustomUser.objects.filter(pk=other.pk).exists())
        self.assertTrue(CustomUser.objects.filter(username='inside_atomic').exists())

    def test_is_editor(self):
        self.assertTrue(activation.is_editor(self.user))
        self.assertTrue(activation.is_editor(make_editor('legacy', account_type=None)))
        self.assertFalse(activation.is_editor(make_editor('cl', account_type='client')))
        self.assertFalse(activation.is_editor(make_editor('sa', account_type='school_admin')))


class ProjectSignalTests(TestCase):
    def setUp(self):
        self.user = make_editor()

    def test_new_project_is_recorded_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            Project.objects.create(user=self.user, title='A', url='https://youtu.be/dQw4w9WgXcQ')
        event = events('project_created').get()
        self.assertEqual(event.props['nth'], 1)
        self.assertEqual(event.props['source'], 'other')
        self.assertEqual(event.props['provider'], 'youtube')
        self.assertIn('seconds_since_signup', event.props)

    def test_source_label_and_nth(self):
        with self.captureOnCommitCallbacks(execute=True):
            with activation.source('welcome'):
                Project.objects.create(user=self.user, title='A', url='https://vimeo.com/1')
            with activation.source('agent'):
                Project.objects.create(user=self.user, title='B')
        sources = list(events('project_created').order_by('id').values_list('props__source', flat=True))
        self.assertEqual(sources, ['welcome', 'agent'])
        self.assertEqual(events('project_created').order_by('-id').first().props['nth'], 2)
        self.assertEqual(activation.current_source(), 'other')  # context restored

    def test_updating_a_project_does_not_count_again(self):
        with self.captureOnCommitCallbacks(execute=True):
            project = Project.objects.create(user=self.user, title='A')
            project.title = 'B'
            project.save()
        self.assertEqual(events('project_created').count(), 1)

    def test_rolled_back_project_is_never_recorded(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    Project.objects.create(user=self.user, title='A')
                    raise RuntimeError('rollback')
            except RuntimeError:
                pass
        self.assertEqual(events('project_created').count(), 0)

    def test_project_gets_created_at(self):
        project = Project.objects.create(user=self.user, title='A')
        self.assertIsNotNone(project.created_at)


class BuilderEventTests(TestCase):
    def setUp(self):
        seed_themes()
        self.user = make_editor()
        self.client.force_login(self.user)

    def test_builder_save_records_source_event_and_first_project_redirect(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(reverse('update_portfolio'), builder_post([project_row('Cut 1')]))
        self.assertRedirects(resp, '/sara/?welcome=1', fetch_redirect_response=False)
        self.assertEqual(events('project_created').get().props['source'], 'builder')
        saved = events('builder_saved').get()
        self.assertEqual((saved.props['flow'], saved.props['projects']), ('update', 1))

    def test_failed_save_records_which_sections_failed(self):
        # A video row with neither a link nor a title (a link alone is enough since the builder cards).
        resp = self.client.post(reverse('update_portfolio'),
                                builder_post([{**project_row('', url=''), 'description': 'Colour and cut'}]))
        self.assertEqual(resp.status_code, 200)
        failed = events('builder_save_failed').get()
        self.assertEqual(failed.props['sections'], ['projects'])

    def test_profile_field_added_events(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('update_portfolio'), builder_post(
                [project_row('Cut 1')], title='Colorist', bio='Hello there', booking_url='calendly.com/sara',
            ))
        fields = sorted(events('profile_field_added').values_list('props__field', flat=True))
        self.assertEqual(fields, ['bio', 'booking_url', 'title'])

    def test_placeholder_title_does_not_count_as_added(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('update_portfolio'), builder_post([project_row('Cut 1')], title='Video Editor'))
        self.assertEqual(events('profile_field_added').count(), 0)


class SignupEventTests(TestCase):
    signup_data = {
        'first_name': 'Nour', 'last_name': 'Hassan', 'username': 'nour_h',
        'email': 'nour@example.com', 'password1': 'Str0ng-pass-99', 'password2': 'Str0ng-pass-99',
    }

    def test_english_editor_signup(self):
        resp = self.client.post(reverse('signup') + '?utm_source=school&utm_campaign=cairo', self.signup_data)
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        user = CustomUser.objects.get(username='nour_h')
        self.assertFalse(user.is_active)
        self.assertEqual(user.user_account.signup_lang, 'en')
        event = events('signup_completed', user).get()
        self.assertEqual(event.props['method'], 'email')
        self.assertEqual(event.props['account_type'], 'editor')
        self.assertEqual(len(mail.outbox), 1)

    def test_campaign_from_landing_visit_is_remembered_for_the_post(self):
        self.client.get(reverse('signup') + '?utm_source=ads&utm_campaign=oct')
        self.client.post(reverse('signup'), self.signup_data)
        props = events('signup_completed').get().props
        self.assertEqual((props['source'], props['campaign']), ('ads', 'oct'))

    def test_arabic_editor_signup_stores_language(self):
        self.client.post(reverse('arabic_signup'), self.signup_data)
        user = CustomUser.objects.get(username='nour_h')
        self.assertEqual(user.user_account.signup_lang, 'ar')
        self.assertEqual(events('signup_completed', user).get().props['lang'], 'ar')

    def test_client_signup_is_recorded_as_client(self):
        self.client.post(reverse('client_signup'), {
            'name': 'Client One', 'email': 'c1@example.com', 'password': 'Str0ng-pass-99',
        })
        user = CustomUser.objects.get(email='c1@example.com')
        self.assertEqual(events('signup_completed', user).get().props['account_type'], 'client')

    def test_email_verified_event(self):
        self.client.post(reverse('signup'), self.signup_data)
        user = CustomUser.objects.get(username='nour_h')
        code = EmailOTP.objects.get(user=user).otp
        self.client.post(reverse('verify_otp'), {'otp': code})
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(events('email_verified', user).count(), 1)


class StatsTests(TestCase):
    def test_wilson_interval(self):
        low, high = wilson_interval(23, 81)
        self.assertAlmostEqual(low, 0.197, places=2)
        self.assertAlmostEqual(high, 0.389, places=2)
        self.assertEqual(wilson_interval(0, 0), (0.0, 0.0))
        low, high = wilson_interval(10, 10)
        self.assertEqual(high, 1.0)
        self.assertGreater(low, 0.7)

    def test_prob_better_matches_the_plan_thresholds(self):
        # Plan §11.3: against the raw 23/81 baseline, 13/30 is ~90%, 12/30 ~88%, 14/30 ~96%.
        p13 = prob_better(13, 30, 23, 81, draws=40_000)
        p12 = prob_better(12, 30, 23, 81, draws=40_000)
        p14 = prob_better(14, 30, 23, 81, draws=40_000)
        self.assertTrue(0.86 < p12 < p13 < p14 < 0.99, (p12, p13, p14))
        self.assertGreaterEqual(p13, 0.88)
        # A clearly worse result is very unlikely to be "better".
        self.assertLess(prob_better(5, 30, 23, 81, draws=20_000), 0.2)

    def test_prob_better_is_deterministic(self):
        self.assertEqual(prob_better(10, 30, 23, 81, draws=5_000), prob_better(10, 30, 23, 81, draws=5_000))


class ActivationReportTests(TestCase):
    def setUp(self):
        site_settings()
        # Cohort window: June 2026.
        self.when = timezone.make_aware(timezone.datetime(2026, 6, 10, 12, 0))
        self.paid_editor = self._user('paid_ed', projects=3, info=True, theme=True)
        self.uploader = self._user('uploader', projects=1, info=True, theme=True)
        self.info_only = self._user('info_only', info=True)
        self.lurker = self._user('lurker')
        self.unverified = self._user('unverified', active=False)
        self.client_user = self._user('a_client', account_type='client')
        self.school_admin = self._user('a_school', account_type='school_admin')
        give_payment(self.paid_editor)
        self.staff = self._user('staff', is_superuser=True)
        self.old_user = self._user('old_timer', when=timezone.make_aware(timezone.datetime(2026, 4, 1)))

    def _user(self, name, projects=0, info=False, theme=False, active=True, account_type='editor',
              when=None, is_superuser=False):
        user = make_editor(name, account_type=account_type, is_active=active, is_superuser=is_superuser)
        CustomUser.objects.filter(pk=user.pk).update(date_joined=when or self.when)
        user.refresh_from_db()
        for i in range(projects):
            Project.objects.create(user=user, title=f'P{i}')
        if info:
            PersonalInfo.objects.create(user=user, full_name=name, title='Editor', email='', phone='', bio='')
        if theme:
            from core.models import Profile
            themes = seed_themes()
            Profile.objects.update_or_create(user=user, defaults={'theme': themes['Creative']})
        return user

    def _run(self, *args):
        out = io.StringIO()
        call_command('activation_report', '--since', '2026-06-01', '--until', '2026-06-30', *args, stdout=out)
        return out.getvalue()

    def test_cohort_excludes_staff_clients_school_admins_unverified_and_out_of_range(self):
        text = self._run()
        self.assertIn('raw signups              7', text)   # 4 editors + unverified + client + school admin
        self.assertIn('- clients                1', text)
        self.assertIn('- school admins          1', text)
        self.assertIn('- never verified         1', text)
        self.assertIn('= real editors           4', text)

    def test_funnel_numbers(self):
        text = self._run()
        self.assertIn('has theme                2', text)
        self.assertIn('has personal info        3', text)
        self.assertIn('>=1 project (ever)       2', text)
        self.assertIn('>=3 projects             1', text)
        self.assertIn('paid                     1', text)
        self.assertIn('paid, no project         0', text)

    def test_activation_window_only_counts_projects_with_a_known_time(self):
        # Backdate: one project 3 days after signup (counts), one 20 days after (doesn't),
        # and one with unknown time (never counts).
        Project.objects.filter(user=self.uploader).update(created_at=self.when + timedelta(days=3))
        Project.objects.filter(user=self.paid_editor).update(created_at=self.when + timedelta(days=20))
        text = self._run('--window-days', '7')
        self.assertIn('>=1 project in 7d       1', text)
        Project.objects.filter(user=self.uploader).update(created_at=None)
        self.assertIn('>=1 project in 7d       0', self._run('--window-days', '7'))

    def test_event_funnel_and_median(self):
        ActivationEvent.objects.create(user=self.uploader, name='welcome_viewed')
        ActivationEvent.objects.create(user=self.uploader, name='link_previewed', props={'ok': True})
        ActivationEvent.objects.create(user=self.uploader, name='project_created',
                                       props={'source': 'welcome', 'seconds_since_signup': 90})
        ActivationEvent.objects.create(user=self.paid_editor, name='project_created',
                                       props={'source': 'builder', 'seconds_since_signup': 300})
        text = self._run()
        self.assertIn('welcome_viewed                         1', text)
        self.assertIn('link_previewed (ok)                    1', text)
        self.assertIn('project_created (source=welcome)       1', text)
        self.assertIn('median signup -> first project         195s  (n=2)', text)

    def test_stalled_csv_segments(self):
        path = os.path.join(tempfile.mkdtemp(), 'stalled.csv')
        self._run('--stalled-csv', path)
        with open(path, encoding='utf-8', newline='') as fh:
            rows = {r['username']: r for r in csv.DictReader(fh)}
        self.assertEqual(rows['lurker']['segment'], 'no_save')
        self.assertEqual(rows['info_only']['segment'], 'info_no_project')
        self.assertEqual(rows['uploader']['segment'], 'uploaded_unpaid')
        self.assertEqual(rows['unverified']['segment'], 'never_verified')
        self.assertNotIn('paid_ed', rows)   # already converted
        self.assertNotIn('a_client', rows)
        self.assertNotIn('staff', rows)

    def test_compare_since_reports_probability(self):
        late = make_editor('late_one')
        CustomUser.objects.filter(pk=late.pk).update(date_joined=timezone.now() - timedelta(days=10))
        Project.objects.create(user=late, title='X')
        Project.objects.filter(user=late).update(created_at=timezone.now() - timedelta(days=9))
        since = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        text = self._run('--compare-since', since, '--draws', '2000')
        self.assertIn('activated within 7d   1/1', text)
        self.assertIn('P(new rate > baseline)', text)

    def test_compare_since_with_no_eligible_signups(self):
        since = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        self.assertIn('Not enough post-launch signups yet.', self._run('--compare-since', since))

    def test_runs_on_an_empty_database(self):
        CustomUser.objects.all().delete()
        out = io.StringIO()
        call_command('activation_report', '--since', '2026-01-01', stdout=out)
        self.assertIn('real editors           0', out.getvalue())
