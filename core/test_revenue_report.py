"""Revenue insights (/revenue-report-exclusive/): definitions, MRR, renewals, forecast and the page."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import revenue_report as rr
from core.models import ManualPayment, Profile, Subscription, UserPayment
from core.testing_helpers import make_editor

NOW = timezone.now


def pay(user, amount=99, days_ago=0, plan_days=30, code=None, status='paid', key=None):
    """A payment dated `days_ago`, with no carried-over time unless a test sets it."""
    sub, _ = Subscription.objects.get_or_create(name=f'Plan{plan_days}', duration=1, days=plan_days)
    p = UserPayment.objects.create(user=user, subscription=sub, amount=amount, status=status,
                                   discount_code_used=code, fawaterk_intent_key=key)
    UserPayment.objects.filter(pk=p.pk).update(date=NOW() - timedelta(days=days_ago), carried_over=None)
    p.refresh_from_db()
    return p


def kpi(report, key):
    return next(k for k in report['kpis'] if k['key'] == key)


class RevenueDefinitionTests(TestCase):
    def setUp(self):
        self.admin = make_editor('boss', is_superuser=True, is_staff=True)

    def test_revenue_counts_confirmed_money_only(self):
        a, b, c = make_editor('a'), make_editor('b'), make_editor('c')
        pay(a, 99, days_ago=3)
        pay(b, 0, days_ago=2, code='FREE100')           # free pass: counted, not revenue
        pay(c, 449, days_ago=1, status='pending')       # not paid
        report = rr.build_report('30')
        self.assertEqual(report['revenue'], Decimal('99'))
        self.assertEqual(report['orders'], 1)
        self.assertEqual(report['discounts']['free_count'], 1)
        self.assertEqual({r['kind'] for r in report['ledger']}, {'new', 'free'})

    def test_team_payments_are_left_out_unless_asked(self):
        pay(self.admin, 99, days_ago=1)
        self.assertEqual(rr.build_report('30')['revenue'], 0)
        self.assertEqual(rr.build_report('30', include_team=True)['revenue'], Decimal('99'))

    def test_mrr_spreads_annual_plans_and_counts_early_renewals_once(self):
        monthly, annual = make_editor('m'), make_editor('y')
        pay(monthly, 99, days_ago=25)
        pay(monthly, 99, days_ago=2)                    # renewed early: both plans are running now
        pay(annual, 449, days_ago=10, plan_days=365)
        report = rr.build_report('30')
        expected = Decimal('99') + Decimal('449') * 30 / 365
        self.assertEqual(report['movement']['end'], expected)
        self.assertEqual(report['movement']['customers_end'], 2)

    def test_mrr_movement_adds_up_and_catches_customers_who_came_and_went(self):
        stayed, left, came = make_editor('stay'), make_editor('left'), make_editor('came')
        pay(stayed, 449, days_ago=100, plan_days=365)
        pay(left, 99, days_ago=80)                      # ran days 80 -> 50 ago, never renewed
        pay(came, 99, days_ago=5)
        mv = rr.build_report('90')['movement']
        a = mv['amounts']
        total = mv['start'] + a.get('new', 0) + a.get('reactivated', 0) + a.get('expansion', 0) \
            - a.get('contraction', 0) - a.get('churned', 0)
        self.assertEqual(total, mv['end'])
        self.assertEqual(mv['counts']['churned'], 1)
        self.assertEqual(mv['counts']['new'], 2)        # "left" joined and churned inside the period

    def test_renewal_outcomes(self):
        renewed, lapsed, waiting = make_editor('r'), make_editor('l'), make_editor('w')
        pay(renewed, 99, days_ago=50)
        pay(renewed, 99, days_ago=15)                   # 5 days after the first ended: inside the grace window
        pay(lapsed, 99, days_ago=60)                    # ended 30 days ago, nothing since
        pay(waiting, 99, days_ago=35)                   # ended 5 days ago: still undecided
        # The renewal itself is still running, so each customer has exactly one ended plan.
        outcomes = rr.renewal_outcomes(rr._load(set(), rr.plan_prices()), NOW())
        states = {o['rec']['cust']: o['state'] for o in outcomes}
        self.assertEqual(states[renewed.id], 'renewed')
        self.assertEqual(states[lapsed.id], 'lapsed')
        self.assertEqual(states[waiting.id], 'pending')
        rate = rr.build_report('90')['renewals']['period']
        self.assertEqual((rate['renewed'], rate['decided'], rate['pending']), (1, 2, 1))
        self.assertEqual(rate['rate'], 50.0)

    def test_renewals_due_and_quiet_customers(self):
        due, later = make_editor('due'), make_editor('later')
        pay(due, 50, days_ago=20, code='HALF')          # paid-up time runs out in 10 days
        pay(later, 449, days_ago=1, plan_days=365)
        Profile.objects.update_or_create(user=due, defaults={'last_seen': NOW() - timedelta(days=20)})
        up = rr.build_report('30')['upcoming']
        self.assertEqual(up['next30']['count'], 1)
        self.assertEqual(up['next30']['value'], Decimal('50'))   # at the price they last paid
        self.assertEqual(up['next30']['quiet'], 1)
        self.assertEqual(up['later_count'], 1)
        self.assertEqual(sum(w['count'] for w in up['weeks']), 1)

    def test_discounts_are_measured_against_list_price(self):
        a, b = make_editor('a'), make_editor('b')
        pay(a, 50, days_ago=3, code='partner')
        pay(b, 0, days_ago=2, code='PARTNER')
        d = rr.build_report('30')['discounts']
        self.assertEqual(d['given'], Decimal('49'))
        self.assertEqual(d['free_value'], Decimal('99'))
        code = d['codes'][0]
        self.assertEqual((code['code'], code['uses'], code['cost']), ('PARTNER', 2, Decimal('148')))

    def test_new_vs_repeat_revenue(self):
        u = make_editor('u')
        pay(u, 99, days_ago=60)
        pay(u, 99, days_ago=29)
        report = rr.build_report('30')
        self.assertEqual(report['new_customers'], 0)
        self.assertEqual(report['ledger'][0]['kind'], 'repeat')


class PeriodTests(TestCase):
    def test_custom_range_is_clamped_to_the_report_start(self):
        p = rr.resolve_period('30', start='2020-01-01', end='2026-06-30', now=NOW())
        self.assertEqual(p.key, 'custom')
        self.assertEqual(timezone.localtime(p.start).date(), rr.REPORT_START_DATE)

    def test_bad_or_reversed_range_falls_back_to_the_preset(self):
        self.assertEqual(rr.resolve_period('30', start='nonsense').key, '30')
        self.assertEqual(rr.resolve_period('90', start='2026-09-10', end='2026-09-01').key, '90')
        self.assertEqual(rr.resolve_period('bogus').key, rr.DEFAULT_PERIOD)

    def test_no_comparison_when_the_previous_period_starts_before_launch(self):
        self.assertIsNone(rr.resolve_period('all').previous)
        now = timezone.make_aware(timezone.datetime(2026, 6, 15))
        self.assertIsNone(rr.resolve_period('30', now=now).previous)   # would start 16 April
        later = timezone.make_aware(timezone.datetime(2026, 10, 15))
        self.assertIsNotNone(rr.resolve_period('30', now=later).previous)


class RevenuePageTests(TestCase):
    def setUp(self):
        self.admin = make_editor('boss', is_superuser=True, is_staff=True)
        self.url = reverse('revenue_report')

    def test_superusers_only(self):
        self.client.force_login(make_editor('nobody'))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_page_renders_with_data(self):
        a, b = make_editor('a', first_name='Mona', last_name='Adel'), make_editor('b')
        pay(a, 99, days_ago=20, code='SKILLIFLY2026')
        pay(b, 449, days_ago=40, plan_days=365)
        ManualPayment.objects.create(user=b, plan_type='monthly', amount_expected=99, sender_identifier='x',
                                     receipt_image='receipts/x.png', status='needs_review')
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'days': '90'})
        self.assertEqual(r.status_code, 200)
        for text in ('Revenue <em>insights</em>', 'What to do about it', 'Mona Adel', 'SKILLIFLY2026',
                     'Remind 1 customer to renew', 'waiting on receipt checks', 'id="rv-data"'):
            self.assertContains(r, text)

    def test_empty_page(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), 'No payments yet')

    def test_old_date_parameters_still_work(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'start_date': '2026-08-01', 'end_date': '2026-08-31'})
        self.assertEqual(r.context['period'].key, 'custom')
        self.assertContains(r, '1 Aug 2026 – 31 Aug 2026')

    def test_csv_export(self):
        pay(make_editor('a', first_name='منى', last_name=''), 99, days_ago=2, code='SAVE')
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'days': '30', 'export': 'csv'})
        self.assertEqual(r['Content-Type'], 'text/csv; charset=utf-8')
        body = r.content.decode('utf-8-sig').splitlines()
        self.assertTrue(body[0].startswith('Date,Customer,Email,Type'))
        self.assertIn('منى', body[1])
        self.assertIn('SAVE', body[1])
