"""PR-5: onboarding nudge emails."""
import io
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.core import mail, signing
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core import nudges
from core.models import ActivationEvent, CustomUser, NudgeLog, Project, UserAccount
from core.testing_helpers import clear_cache, give_payment, make_editor, site_settings


def add_projects(user, n):
    for i in range(n):
        Project.objects.create(user=user, title=f'P{i}')


class RuleTests(TestCase):
    def due(self, user):
        return nudges.due_key(user)

    def test_no_project_windows(self):
        cases = (
            (0, 0.5, None),       # too new
            (0, 2, 'no_project_1h'),
            (0, 23.5, 'no_project_1h'),   # contiguous windows: no gap
            (0, 24, 'no_project_24h'),
            (0, 30, 'no_project_24h'),
            (0, 50, 'no_project_24h'),
            (0, 71.9, 'no_project_24h'),
            (0, 72, 'no_project_72h'),
            (0, 100, 'no_project_72h'),
            (0, 150, None),       # day 6.25: between windows
            (0, 7.5 * 24, 'no_project_7d'),
            (0, 9 * 24, None),    # given up
        )
        for i, (projects, hours, expected) in enumerate(cases):
            user = make_editor(f'u{i}', hours_old=hours)
            add_projects(user, projects)
            self.assertEqual(self.due(user), expected, (projects, hours))

    def test_one_or_two_projects_get_the_add_more_nudge_after_48h(self):
        young = make_editor('young', hours_old=30)
        add_projects(young, 1)
        self.assertIsNone(self.due(young))
        older = make_editor('older', hours_old=50)
        add_projects(older, 2)
        self.assertEqual(self.due(older), 'few_projects_48h')

    def test_three_projects_unpaid_get_the_go_live_nudge(self):
        user = make_editor('ready', days_old=4)
        add_projects(user, 3)
        self.assertEqual(self.due(user), 'ready_unpaid_3d')
        give_payment(user)
        self.assertIsNone(self.due(user))

    def test_each_key_is_sent_at_most_once(self):
        user = make_editor('once', hours_old=30)
        self.assertEqual(self.due(user), 'no_project_24h')
        NudgeLog.objects.create(user=user, key='no_project_24h')
        self.assertIsNone(self.due(user))

    def test_windows_never_overlap_for_one_user_state(self):
        # At any age a user in a given project state matches at most one rule.
        for projects in (0, 1, 2, 3):
            for hours in range(0, 12 * 24, 3):
                user_age = timedelta(hours=hours)
                matches = [
                    key for key, lo, hi, test in nudges.RULES
                    if lo <= user_age < hi and test(projects, False)
                ]
                self.assertLessEqual(len(matches), 1, (projects, hours, matches))


class EligibilityTests(TestCase):
    def ids(self):
        return set(nudges.eligible_users().values_list('username', flat=True))

    def test_only_active_unopted_recent_editors(self):
        make_editor('good', hours_old=5)
        make_editor('inactive', hours_old=5, is_active=False)
        make_editor('buyer', hours_old=5, account_type='client')
        make_editor('school', hours_old=5, account_type='school_admin')
        make_editor('staff', hours_old=5, is_superuser=True)
        make_editor('alex_mercer', hours_old=5)
        make_editor('stale', days_old=30)
        quiet = make_editor('quiet', hours_old=5)
        UserAccount.objects.filter(user=quiet).update(email_opt_out=True)
        make_editor('legacy', hours_old=5, account_type=None)
        self.assertEqual(self.ids(), {'good', 'legacy'})


class SendTests(TestCase):
    def setUp(self):
        clear_cache()
        self.user = make_editor('sara', hours_old=2)
        UserAccount.objects.filter(user=self.user).update(signup_lang='en')

    def test_sends_once_logs_and_tracks(self):
        self.assertTrue(nudges.send_nudge(self.user, 'no_project_1h'))
        self.assertFalse(nudges.send_nudge(self.user, 'no_project_1h'))  # second call: no double send
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NudgeLog.objects.filter(user=self.user, key='no_project_1h').count(), 1)
        self.assertEqual(ActivationEvent.objects.get(name='nudge_sent').props['key'], 'no_project_1h')

    def test_email_content_links_and_headers(self):
        nudges.send_nudge(self.user, 'no_project_1h')
        message = mail.outbox[0]
        self.assertEqual(message.to, ['sara@example.com'])
        self.assertEqual(message.subject, 'Your portfolio is 60 seconds away')
        self.assertIn('Hi Sara', message.body)
        self.assertIn('https://skillifly.cloud/welcome/?utm_source=nudge&utm_campaign=no_project_1h', message.body)
        self.assertIn('/email/unsubscribe/', message.body)
        self.assertNotIn('&amp;', message.body)    # plain text must not be HTML-escaped
        self.assertNotIn('&#x27;', message.body)
        self.assertIn("You've signed up", message.body)
        self.assertIn('/email/unsubscribe/', message.extra_headers['List-Unsubscribe'])
        html = message.alternatives[0][0]
        self.assertIn('Add my first video', html)
        self.assertIn('utm_source=nudge&amp;utm_campaign=no_project_1h', html)  # escaped correctly in HTML
        self.assertNotIn('dir="rtl"', html)

    def test_query_string_links_use_ampersand(self):
        add_projects(self.user, 1)
        nudges.send_nudge(self.user, 'few_projects_48h', project_count=1)
        self.assertIn('/welcome/?add=1&utm_source=nudge&utm_campaign=few_projects_48h', mail.outbox[0].body)
        self.assertIn('You have 1 video so far', mail.outbox[0].body)

    def test_arabic_user_gets_arabic(self):
        UserAccount.objects.filter(user=self.user).update(signup_lang='ar')
        self.user.refresh_from_db()
        nudges.send_nudge(self.user, 'no_project_1h')
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'معرض أعمالك على بُعد دقيقة واحدة')
        self.assertIn('/ar/welcome/?utm_source=nudge', message.body)
        self.assertIn('dir="rtl"', message.alternatives[0][0])
        self.assertNotIn('60 seconds', message.body)

    def test_unknown_language_gets_both_arabic_first(self):
        UserAccount.objects.filter(user=self.user).update(signup_lang='')
        self.user.refresh_from_db()
        nudges.send_nudge(self.user, 'no_project_1h')
        message = mail.outbox[0]
        self.assertIn('·', message.subject)
        self.assertLess(message.subject.index('معرض'), message.subject.index('portfolio'))
        self.assertIn('/ar/welcome/', message.body)
        self.assertIn('/welcome/?utm', message.body)

    def test_founder_email_is_plain_with_no_button(self):
        nudges.send_nudge(self.user, 'no_project_72h')
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Quick question')
        self.assertIn('hit reply', message.body)
        self.assertNotIn('/welcome/', message.body)
        self.assertNotIn('<a href="https://skillifly.cloud/welcome', message.alternatives[0][0])

    @override_settings(NUDGE_FOUNDER_NAME='Ahmed')
    def test_founder_name_is_used_when_configured(self):
        nudges.send_nudge(self.user, 'no_project_72h')
        self.assertIn("I'm Ahmed, I built Skillifly", mail.outbox[0].body)

    def test_go_live_email_points_at_payment_and_the_public_url(self):
        add_projects(self.user, 3)
        nudges.send_nudge(self.user, 'ready_unpaid_3d', project_count=3)
        body = mail.outbox[0].body
        self.assertIn('/payment/?utm_source=nudge', body)
        self.assertIn('skillifly.cloud/sara', body)
        self.assertIn('3 videos', body)

    def test_failed_send_is_retried_next_run(self):
        with patch.object(EmailMultiAlternatives, 'send', side_effect=OSError('smtp down')):
            self.assertFalse(nudges.send_nudge(self.user, 'no_project_1h'))
        self.assertEqual(NudgeLog.objects.count(), 0)
        self.assertEqual(ActivationEvent.objects.filter(name='nudge_sent').count(), 0)
        self.assertTrue(nudges.send_nudge(self.user, 'no_project_1h'))

    def test_every_key_renders_in_both_languages(self):
        add_projects(self.user, 2)
        for key in nudges.KEYS:
            for lang in ('en', 'ar'):
                UserAccount.objects.filter(user=self.user).update(signup_lang=lang)
                self.user.refresh_from_db()
                subject, text, html = nudges.render_nudge(self.user, key, project_count=2)
                self.assertTrue(subject and text and html, (key, lang))
                self.assertNotIn('{', text, (key, lang))   # no unformatted placeholders
                self.assertNotIn('{{', html)


class QuietHoursTests(TestCase):
    def test_cairo_quiet_hours(self):
        utc = dt_timezone.utc
        for hour, quiet in ((20, True), (23, True), (1, True), (12, False), (15, False)):
            moment = datetime(2026, 10, 16, hour, 30, tzinfo=utc)
            self.assertEqual(nudges.in_quiet_hours(moment), quiet, hour)


class CommandTests(TestCase):
    def setUp(self):
        clear_cache()
        self.user = make_editor('sara', hours_old=2)
        self.quiet = patch('core.nudges.in_quiet_hours', return_value=False)
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def run_cmd(self, *args):
        out = io.StringIO()
        call_command('send_onboarding_nudges', *args, stdout=out)
        return out.getvalue()

    def test_disabled_switch_sends_nothing(self):
        site_settings(nudges_enabled=False)
        self.assertIn('disabled', self.run_cmd())
        self.assertEqual(len(mail.outbox), 0)

    def test_enabled_sends_and_is_idempotent(self):
        site_settings(nudges_enabled=True)
        self.assertIn('Sent 1 nudge(s).', self.run_cmd())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Sent 0 nudge(s).', self.run_cmd())  # same hour again: nothing new
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_sends_and_writes_nothing_even_when_disabled(self):
        site_settings(nudges_enabled=False)
        out = self.run_cmd('--dry-run')
        self.assertIn('would send no_project_1h -> sara@example.com', out)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NudgeLog.objects.count(), 0)

    def test_quiet_hours_skip_the_run(self):
        site_settings(nudges_enabled=True)
        self.quiet.stop()
        with patch('core.nudges.in_quiet_hours', return_value=True):
            self.assertIn('Quiet hours', self.run_cmd())
            self.assertEqual(len(mail.outbox), 0)
            self.run_cmd('--ignore-quiet-hours')
            self.assertEqual(len(mail.outbox), 1)
        self.quiet.start()

    def test_limit_and_only(self):
        site_settings(nudges_enabled=True)
        make_editor('b', hours_old=3)
        make_editor('c', hours_old=30)
        self.assertIn('Sent 1 nudge(s).', self.run_cmd('--limit', '1'))
        self.assertEqual([m.to[0] for m in mail.outbox], ['c@example.com'])  # oldest account first
        mail.outbox.clear()
        self.run_cmd('--only', 'no_project_1h')
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['b@example.com', 'sara@example.com'])

    def test_users_who_already_added_a_video_are_not_nagged(self):
        site_settings(nudges_enabled=True)
        add_projects(self.user, 1)
        self.run_cmd()
        self.assertEqual(len(mail.outbox), 0)

    def test_opted_out_user_gets_nothing(self):
        site_settings(nudges_enabled=True)
        UserAccount.objects.filter(user=self.user).update(email_opt_out=True)
        self.run_cmd()
        self.assertEqual(len(mail.outbox), 0)

    def test_one_email_per_user_per_run(self):
        site_settings(nudges_enabled=True)
        self.run_cmd()
        self.assertEqual(NudgeLog.objects.filter(user=self.user).count(), 1)


class UnsubscribeTests(TestCase):
    def setUp(self):
        self.user = make_editor('sara', hours_old=2)

    def url(self, user=None):
        return reverse('email_unsubscribe', args=[signing.dumps((user or self.user).pk, salt='nudge-unsub')])

    def test_get_only_confirms(self):
        resp = self.client.get(self.url())
        self.assertContains(resp, 'Stop onboarding emails?')
        self.assertFalse(UserAccount.objects.get(user=self.user).email_opt_out)

    def test_post_opts_out_without_login(self):
        resp = self.client.post(self.url())
        self.assertContains(resp, "You're unsubscribed")
        self.assertTrue(UserAccount.objects.get(user=self.user).email_opt_out)
        self.assertNotIn(self.user, list(nudges.eligible_users()))

    def test_tampered_or_foreign_tokens_404(self):
        other = make_editor('other')
        token = signing.dumps(self.user.pk, salt='nudge-unsub')
        self.assertEqual(self.client.post(reverse('email_unsubscribe', args=[token + 'x'])).status_code, 404)
        self.assertEqual(self.client.post(reverse('email_unsubscribe', args=['garbage'])).status_code, 404)
        wrong_salt = signing.dumps(other.pk, salt='something-else')
        self.assertEqual(self.client.post(reverse('email_unsubscribe', args=[wrong_salt])).status_code, 404)
        self.assertFalse(UserAccount.objects.get(user=other).email_opt_out)

    def test_legacy_user_without_account_row_can_unsubscribe(self):
        legacy = make_editor('legacy', account_type=None)
        self.client.post(self.url(legacy))
        self.assertTrue(UserAccount.objects.get(user=legacy).email_opt_out)

    def test_unsubscribe_link_in_a_real_email_works(self):
        nudges.send_nudge(self.user, 'no_project_1h')
        link = mail.outbox[0].extra_headers['List-Unsubscribe'].strip('<>')
        path = link.replace('https://skillifly.cloud', '')
        self.client.post(path)
        self.assertTrue(UserAccount.objects.get(user=self.user).email_opt_out)
