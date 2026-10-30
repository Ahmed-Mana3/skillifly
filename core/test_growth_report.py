"""Executive overview (/admin-dashboard-exclusive/): signup outcomes, acquisition, scorecard and the page."""
from datetime import timedelta

from allauth.socialaccount.models import SocialAccount
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import growth_report as gr
from core.models import HeardAboutResponse, Profile, Project, UserAccount
from core.test_revenue_report import pay
from core.testing_helpers import make_editor


def video(user):
    return Project.objects.create(user=user, title='Reel', url='https://youtu.be/x')


def kpi(report, key):
    return next(k for k in report['growth_kpis'] + report['money_kpis'] if k['key'] == key)


class GrowthReportTests(TestCase):
    def setUp(self):
        self.admin = make_editor('boss', is_superuser=True, is_staff=True)

    def test_every_signup_has_one_outcome(self):
        paid, built, idle = make_editor('p', days_old=3), make_editor('b', days_old=2), make_editor('i', days_old=1)
        video(built)
        pay(paid, 99, days_ago=1)
        report = gr.build_report('30')
        self.assertEqual(report['signups'], 3)                     # the superuser is team, left out
        self.assertEqual({o['key']: o['count'] for o in report['outcomes']}, {'paid': 1, 'built': 1, 'new': 1})
        self.assertEqual(sum(p['signups'] for p in report['trend']['points']), 3)
        funnel = {s['key']: s['count'] for s in report['funnel']}
        self.assertEqual((funnel['signed_up'], funnel['project'], funnel['subscribed']), (3, 1, 1))
        self.assertEqual(kpi(report, 'conversion')['value'], '33.3%')

    def test_clients_and_old_signups_do_not_count(self):
        make_editor('client', account_type='client', days_old=1)
        make_editor('old', days_old=200)
        make_editor('new', days_old=1)
        self.assertEqual(gr.build_report('30')['signups'], 1)
        self.assertEqual(gr.build_report('30', include_team=True)['signups'], 2)   # plus the superuser

    def test_signups_change_against_the_previous_period(self):
        for i in range(8):
            make_editor(f'old{i}', days_old=40)
        for i in range(4):
            make_editor(f'new{i}', days_old=5)
        report = gr.build_report('30')
        self.assertEqual(kpi(report, 'signups')['delta']['value'], -50)
        self.assertIn('down 50%', report['summary'][0])
        self.assertTrue(any(i['title'].startswith('Signups are down 50%') for i in report['insights']))

    def test_acquisition_segments(self):
        users = [make_editor(f'u{i}', days_old=2) for i in range(6)]
        for u in users[:5]:
            HeardAboutResponse.objects.create(user=u, source='instagram')
        SocialAccount.objects.create(user=users[0], provider='google', uid='g1')
        UserAccount.objects.filter(user__in=users[:2]).update(signup_lang='ar')
        pay(users[0], 99, days_ago=1)
        seg = gr.build_report('30')['segments']
        groups = {g['key']: {r['key']: r for r in g['rows']} for g in seg['groups']}
        insta = groups['source']['instagram']
        self.assertEqual((insta['signups'], insta['paid'], insta['paid_pct'], insta['small']), (5, 1, 20.0, False))
        self.assertEqual(groups['source']['none']['signups'], 1)
        self.assertEqual(groups['method']['google']['signups'], 1)
        self.assertEqual(groups['lang']['ar']['signups'], 2)
        self.assertEqual(seg['answered'], 5)

    def test_scorecard_counts_this_week(self):
        u = make_editor('u', hours_old=1)
        pay(u, 99)
        week = gr.build_report('30')['scorecard'][0]
        self.assertTrue(week['current'])
        self.assertEqual((week['signups'], week['new_paying'], week['revenue_label'], week['paying']), (1, 1, '99', 1))

    def test_upgrade_candidates_become_a_decision(self):
        u = make_editor('ready', days_old=3)
        video(u)
        Profile.objects.update_or_create(user=u, defaults={'last_seen': timezone.now() - timedelta(hours=2)})
        titles = [i['title'] for i in gr.build_report('30')['insights']]
        self.assertIn('1 free editor is ready to upgrade', titles)


class AdminDashboardPageTests(TestCase):
    def setUp(self):
        self.admin = make_editor('boss', is_superuser=True, is_staff=True)
        self.url = reverse('admin_dashboard')

    def test_superusers_only(self):
        self.client.force_login(make_editor('nobody'))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_page_renders_with_data(self):
        a = make_editor('a', first_name='Mona', last_name='Adel', days_old=2)
        video(a)
        pay(a, 99, days_ago=1)
        make_editor('b', days_old=1)
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'days': '90'})
        self.assertEqual(r.status_code, 200)
        for text in ('How Skillifly is <em>doing</em>', 'The short version', 'Needs a decision',
                     'From signup to paying customer', 'Where the editors who pay come from', 'Week by week',
                     'Mona Adel', 'id="gr-data"', 'class="gr-spark"'):
            self.assertContains(r, text)

    def test_empty_page(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), 'Nothing to show yet')

    def test_old_date_parameters_still_work(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'start_date': '2026-08-01', 'end_date': '2026-08-31', 'period': 'week'})
        self.assertEqual(r.context['period'].key, 'custom')

    def test_csv_export_has_everyone_with_their_phone(self):
        u = make_editor('mona', first_name='منى', last_name='', days_old=1)
        Profile.objects.update_or_create(user=u, defaults={'phone_number': '01000000000'})
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'days': '30', 'export': 'csv'})
        self.assertEqual(r['Content-Type'], 'text/csv; charset=utf-8')
        body = r.content.decode('utf-8-sig').splitlines()
        self.assertTrue(body[0].startswith('Signed up,Name,Username,Email,Phone'))
        self.assertEqual(len(body), 2)
        self.assertIn('منى', body[1])
        self.assertIn('01000000000', body[1])
