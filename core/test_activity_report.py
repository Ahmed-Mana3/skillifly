"""User activity report (/user-activity/): definitions, contact lists, filters and exports."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import activity_report as ar
from core.models import AnalyticsVisit, PersonalInfo, Profile, Project, Skill, Subscription, UserPayment
from core.testing_helpers import give_payment, make_editor

NOW = timezone.now


def seen(user, **ago):
    Profile.objects.update_or_create(user=user, defaults={'last_seen': NOW() - timedelta(**ago)})


def free_pass(user):
    sub, _ = Subscription.objects.get_or_create(name='Plan30', duration=1, days=30)
    return UserPayment.objects.create(user=user, subscription=sub, amount=0, status='paid',
                                      fawaterk_intent_key=f'MANUAL-COUPON-{user.pk}')


class ActivityReportTests(TestCase):
    def setUp(self):
        self.admin = make_editor('boss', is_superuser=True, is_staff=True)

    def person(self, report, user):
        return next(p for p in report['people'] if p['id'] == user.id)

    # ── Definitions ────────────────────────────────────────────────────────

    def test_recency_buckets_split_lapsed_from_left_on_day_one(self):
        today = make_editor('today_u', days_old=3)
        seen(today, hours=2)
        lapsed = make_editor('lapsed_u', days_old=90)
        seen(lapsed, days=40)
        gone = make_editor('gone_u', days_old=90)
        seen(gone, days=90, hours=-1)  # an hour after signing up, never again

        report = ar.build_report('30')
        self.assertEqual(self.person(report, today)['recency'], 'today')
        self.assertEqual(self.person(report, lapsed)['recency'], 'lapsed')
        self.assertEqual(self.person(report, gone)['recency'], 'one_day')
        self.assertFalse(self.person(report, gone)['returned'])

    def test_plan_states(self):
        paying, pass_user, expired, free = (make_editor(n) for n in ('pay', 'pass', 'exp', 'free'))
        give_payment(paying)
        free_pass(pass_user)
        give_payment(expired, days_ago=40)

        report = ar.build_report('30')
        self.assertEqual(self.person(report, paying)['plan_state'], 'paying')
        self.assertEqual(self.person(report, pass_user)['plan_state'], 'free_pass')
        self.assertEqual(self.person(report, expired)['plan_state'], 'expired')
        self.assertEqual(self.person(report, free)['plan_state'], 'free')
        paying_kpi = next(k for k in report['kpis'] if k['key'] == 'paying')
        self.assertEqual(paying_kpi['value'], '1')

    def test_paying_change_is_against_period_start(self):
        old = make_editor('old_pay', days_old=60)
        give_payment(old, days_ago=40, plan_days=365)
        new = make_editor('new_pay', days_old=5)
        give_payment(new, days_ago=2)
        paying_kpi = next(k for k in ar.build_report('7')['kpis'] if k['key'] == 'paying')
        self.assertEqual(paying_kpi['value'], '2')
        self.assertEqual(paying_kpi['delta']['label'], '+100%')

    def test_team_mock_and_client_accounts_are_left_out(self):
        make_editor('alex_mercer')
        client = make_editor('a_client', account_type='client')
        editor = make_editor('an_editor')
        ids = {p['id'] for p in ar.build_report()['people']}
        self.assertEqual(ids, {editor.id})
        everyone = {p['id'] for p in ar.build_report(audience='all', include_team=True)['people']}
        self.assertEqual(everyone, {editor.id, client.id, self.admin.id})

    def test_setup_milestones_and_return_rate_for_period_signups(self):
        done = make_editor('done_u', days_old=5)
        PersonalInfo.objects.create(user=done, full_name='Done U', title='Editor', email='d@x.com', phone='1', bio='b')
        Project.objects.create(user=done, title='Reel')
        Skill.objects.create(user=done, name='Premiere')
        done.user_account.launch_theme_picked = True
        done.user_account.save()
        seen(done, days=1)
        idle = make_editor('idle_u', days_old=5)
        seen(idle, days=5)
        make_editor('older_u', days_old=40)  # outside the 30-day cohort

        report = ar.build_report('30')
        cohort = report['cohort']
        self.assertEqual(cohort['signups'], 2)
        self.assertEqual(cohort['counts']['launched'], 1)
        self.assertEqual(cohort['activation'], 50.0)
        self.assertEqual(cohort['return_rate'], 50.0)
        self.assertEqual(self.person(report, done)['xp'], 100)

    # ── Report start (1 May 2026) ──────────────────────────────────────────

    def test_nothing_before_the_report_start_counts(self):
        from core.payment_report import report_start
        start = report_start()
        early = make_editor('launch_era')
        type(early).objects.filter(pk=early.pk).update(date_joined=start - timedelta(days=3))
        user = make_editor('may_user')
        old_payment = give_payment(user)
        UserPayment.objects.filter(pk=old_payment.pk).update(date=start - timedelta(days=1))
        old_visit = AnalyticsVisit.objects.create(user=user, session_id='old', user_agent='Mozilla/5.0')
        AnalyticsVisit.objects.filter(pk=old_visit.pk).update(created_at=start - timedelta(days=1))

        report = ar.build_report('all')
        self.assertEqual([p['username'] for p in report['people']], ['may_user'])
        person = self.person(report, user)
        self.assertEqual(person['plan_state'], 'free')
        self.assertIsNone(person['last_visit'])
        self.assertEqual(report['period'].start, start)
        self.assertIn('since 1 May 2026', report['period'].label)

    def test_periods_are_cut_at_the_report_start_and_never_compared_with_a_cut_window(self):
        from core.payment_report import report_start
        start = report_start()
        early = ar.resolve_period('90', now=start + timedelta(days=50))
        self.assertEqual(early.start, start)
        self.assertIn('from 1 May 2026', early.label)
        self.assertIsNone(early.previous)
        self.assertIsNone(ar.resolve_period('90', now=start + timedelta(days=120)).previous)
        self.assertEqual(ar.resolve_period('90', now=start + timedelta(days=200)).previous.days, 90)

    # ── Who to contact ─────────────────────────────────────────────────────

    def test_contact_lists(self):
        renew = make_editor('renew_u', days_old=40)
        give_payment(renew, days_ago=25)
        seen(renew, hours=3)
        quiet = make_editor('quiet_u', days_old=60)
        give_payment(quiet, days_ago=1, plan_days=365)
        seen(quiet, days=20)
        lapsed = make_editor('lapsed_pay', days_old=60)
        give_payment(lapsed, days_ago=40)
        ready = make_editor('ready_u', days_old=3)
        Project.objects.create(user=ready, title='Edit')
        seen(ready, hours=1)
        make_editor('cold_free', days_old=3)  # no videos: not ready to upgrade

        lists = {c['key']: c for c in ar.build_report('30')['contact_lists']}
        names = {k: [r['username'] for r in c['rows']] for k, c in lists.items()}
        self.assertEqual(names['renewals'], ['renew_u'])
        self.assertEqual(names['quiet'], ['quiet_u'])
        self.assertEqual(names['winback'], ['lapsed_pay'])
        self.assertEqual(names['upgrade'], ['ready_u'])
        self.assertEqual(lists['quiet']['value'], '449')

    def test_portfolio_visits_skip_bots(self):
        user = make_editor('seen_pf')
        AnalyticsVisit.objects.create(user=user, session_id='a', user_agent='Mozilla/5.0')
        AnalyticsVisit.objects.create(user=user, session_id='b', user_agent='Googlebot/2.1')
        report = ar.build_report('7')
        self.assertEqual(self.person(report, user)['visits'], 1)
        self.assertEqual(report['traction']['visits'], 1)

    # ── Page ───────────────────────────────────────────────────────────────

    def test_superusers_only(self):
        self.client.force_login(make_editor('plain'))
        self.assertEqual(self.client.get(reverse('user_activity_report')).status_code, 302)

    def test_page_renders_every_period_and_audience(self):
        user = make_editor('visible_u', days_old=10)
        give_payment(user, days_ago=25)
        self.client.force_login(self.admin)
        for days in ('7', '30', '90', 'all'):
            for audience in ('editors', 'all'):
                response = self.client.get(reverse('user_activity_report'), {'days': days, 'audience': audience})
                self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'How recently people used Skillifly')
        self.assertContains(response, 'Who to contact')
        self.assertContains(response, 'visible_u@example.com')

    def test_empty_state(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('user_activity_report')), 'No users to report on yet')

    def test_directory_filters_and_pagination(self):
        payer = make_editor('payer_x')
        give_payment(payer)
        for i in range(ar.PAGE_SIZE + 5):
            make_editor(f'bulk{i}')
        self.client.force_login(self.admin)
        url = reverse('user_activity_report')

        response = self.client.get(url, {'plan': 'paying'})
        self.assertEqual(response.context['directory_count'], 1)
        response = self.client.get(url, {'q': '@payer'})
        self.assertEqual([p['username'] for p in response.context['page'].object_list], ['payer_x'])
        response = self.client.get(url)
        self.assertEqual(response.context['directory_count'], ar.PAGE_SIZE + 6)
        self.assertIn('page=2', response.context['next_href'])
        self.assertEqual(len(self.client.get(url, {'page': 2}).context['page'].object_list), 6)

    def test_csv_exports(self):
        quiet = make_editor('quiet_csv', days_old=60)
        give_payment(quiet)
        seen(quiet, days=20)
        make_editor('other_csv')
        self.client.force_login(self.admin)
        url = reverse('user_activity_report')

        response = self.client.get(url, {'export': 'users', 'plan': 'paying'})
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        body = response.content.decode('utf-8-sig').splitlines()
        self.assertEqual(len(body), 2)
        self.assertIn('quiet_csv', body[1])

        body = self.client.get(url, {'export': 'quiet'}).content.decode('utf-8-sig').splitlines()
        self.assertIn('Why', body[0])
        self.assertIn('Not seen for 20 days', body[1])
