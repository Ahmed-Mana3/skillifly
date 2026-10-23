import json
import re
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import CustomUser, PaymentTrackingEvent, Subscription, UserPayment

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
BOT_UA = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


def _rendered_vid(response):
    """Pull the visitor id the tracker partial handed to payment_funnel.js."""
    match = re.search(r"vid: '([^']*)'", response.content.decode())
    return match.group(1) if match else ''


class PaymentFunnelIdentityTests(TestCase):
    """The page view and the click beacon must land on one visitor id."""

    def setUp(self):
        self.client = Client()
        self.client.defaults['HTTP_USER_AGENT'] = UA

    def test_page_view_records_a_visitor_id(self):
        response = self.client.get(reverse('payment'))
        self.assertEqual(response.status_code, 200)
        event = PaymentTrackingEvent.objects.get()
        self.assertEqual(event.event_type, 'page_view')
        self.assertEqual(event.page, 'payment')
        self.assertTrue(event.session_id.startswith('pvid_'))
        self.assertIsNone(event.user)

    def test_rendered_vid_matches_recorded_session_id(self):
        response = self.client.get(reverse('payment'))
        event = PaymentTrackingEvent.objects.get()
        self.assertEqual(_rendered_vid(response), event.session_id)

    def test_click_merges_with_the_page_view_of_the_same_visitor(self):
        response = self.client.get(reverse('payment'))
        vid = _rendered_vid(response)
        self.client.cookies['sf_payment_vid'] = vid

        self.client.post(
            reverse('payment_funnel_track'),
            data=json.dumps({
                'page': 'payment',
                'action': 'plan_monthly',
                'plan_type': 'monthly',
            }),
            content_type='text/plain;charset=UTF-8',
        )

        self.assertEqual(PaymentTrackingEvent.objects.count(), 2)
        self.assertEqual(
            PaymentTrackingEvent.objects.values('session_id').distinct().count(), 1
        )

    def test_click_merges_via_the_session_when_the_vid_cookie_is_missing(self):
        """Cookie-less clients (blocked cookies) still merge via the session."""
        self.client.get(reverse('payment'))
        self.client.post(
            reverse('payment_funnel_track'),
            data=json.dumps({'page': 'payment', 'action': 'plan_monthly'}),
            content_type='application/json',
        )
        self.assertEqual(PaymentTrackingEvent.objects.count(), 2)
        self.assertEqual(
            PaymentTrackingEvent.objects.values('session_id').distinct().count(), 1
        )

    def test_identity_survives_the_whole_flow(self):
        response = self.client.get(reverse('payment'))
        vid = _rendered_vid(response)
        self.client.cookies['sf_payment_vid'] = vid

        for path, action in (
            (reverse('payment'), 'plan_monthly'),
            (reverse('manual_payment', kwargs={'plan_type': 'monthly'}), 'continue'),
            (reverse('payment_success'), 'go_dashboard'),
        ):
            self.client.get(path)
            self.client.post(
                reverse('payment_funnel_track'),
                data=json.dumps({'page': 'payment', 'action': action}),
                content_type='application/json',
            )

        self.assertEqual(
            PaymentTrackingEvent.objects.values('session_id').distinct().count(), 1
        )

    def test_repeat_opens_of_one_visitor_merge(self):
        for _ in range(3):
            self.client.get(reverse('payment'))
        self.assertEqual(PaymentTrackingEvent.objects.count(), 3)
        self.assertEqual(
            PaymentTrackingEvent.objects.values('session_id').distinct().count(), 1
        )

    def test_two_visitors_stay_separate(self):
        other = Client()
        other.defaults['HTTP_USER_AGENT'] = UA
        self.client.get(reverse('payment'))
        other.get(reverse('payment'))
        self.assertEqual(
            PaymentTrackingEvent.objects.values('session_id').distinct().count(), 2
        )

    def test_tracker_script_loads_for_staff_too(self):
        admin = CustomUser.objects.create_user(
            username='admin_ui', email='admin_ui@example.com',
            password='Password123!', is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        response = self.client.get(reverse('payment'))
        self.assertContains(response, 'payment_funnel.js')
        self.assertTrue(_rendered_vid(response))


class PaymentFunnelEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.defaults['HTTP_USER_AGENT'] = UA

    def _post(self, payload, content_type='application/json'):
        return self.client.post(
            reverse('payment_funnel_track'),
            data=json.dumps(payload) if isinstance(payload, dict) else payload,
            content_type=content_type,
        )

    def test_beacon_text_plain_body_is_accepted(self):
        response = self._post(
            {'page': 'payment', 'action': 'plan_annual', 'plan_type': 'pro_annual'},
            content_type='text/plain;charset=UTF-8',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        event = PaymentTrackingEvent.objects.get()
        self.assertEqual(event.event_type, 'click')
        self.assertEqual(event.action, 'plan_annual')
        self.assertEqual(event.plan_type, 'pro_annual')

    def test_missing_page_is_rejected(self):
        self.assertEqual(self._post({'action': 'plan_monthly'}).status_code, 400)
        self.assertEqual(PaymentTrackingEvent.objects.count(), 0)

    def test_unknown_page_is_rejected(self):
        self.assertEqual(self._post({'page': 'evil', 'action': 'x'}).status_code, 400)
        self.assertEqual(PaymentTrackingEvent.objects.count(), 0)

    def test_unknown_plan_type_is_dropped(self):
        self._post({'page': 'payment', 'action': 'plan_monthly', 'plan_type': 'lifetime'})
        self.assertEqual(PaymentTrackingEvent.objects.get().plan_type, '')

    def test_malformed_body_is_rejected(self):
        self.assertEqual(self._post('not json').status_code, 400)
        self.assertEqual(self._post('[1, 2, 3]').status_code, 400)
        self.assertEqual(PaymentTrackingEvent.objects.count(), 0)

    def test_get_is_not_allowed(self):
        self.assertEqual(
            self.client.get(reverse('payment_funnel_track')).status_code, 405
        )

    def test_bot_clicks_are_ignored(self):
        self.client.defaults['HTTP_USER_AGENT'] = BOT_UA
        self._post({'page': 'payment', 'action': 'plan_monthly'})
        self.assertEqual(PaymentTrackingEvent.objects.count(), 0)

    def test_staff_clicks_are_tracked(self):
        """Admins are real visitors too - their opens must show up."""
        admin = CustomUser.objects.create_user(
            username='admin_bo', email='admin@example.com',
            password='Password123!', is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        self.client.get(reverse('payment'))
        self._post({'page': 'payment', 'action': 'plan_monthly'})
        events = PaymentTrackingEvent.objects.all()
        self.assertEqual(events.count(), 2)
        self.assertEqual({e.user for e in events}, {admin})

    def test_paid_user_opens_and_clicks_are_tracked(self):
        user = CustomUser.objects.create_user(
            username='paid_bo', email='paid@example.com', password='Password123!'
        )
        Subscription.objects.create(name='Pro', duration=30, days=30)
        UserPayment.objects.create(
            user=user, subscription=Subscription.objects.get(name='Pro'), status='paid'
        )
        self.client.force_login(user)
        self.client.get(reverse('payment'))
        self._post({'page': 'payment', 'action': 'plan_annual', 'plan_type': 'pro_annual'})
        self.assertEqual(PaymentTrackingEvent.objects.count(), 2)
        self.assertEqual(
            {e.user for e in PaymentTrackingEvent.objects.all()}, {user}
        )

    def test_clicks_are_attributed_to_a_logged_in_user(self):
        user = CustomUser.objects.create_user(
            username='editor_bo', email='editor@example.com', password='Password123!'
        )
        self.client.force_login(user)
        self._post({'page': 'manual_payment', 'action': 'method_instapay'})
        event = PaymentTrackingEvent.objects.get()
        self.assertEqual(event.user, user)
        self.assertEqual(event.action, 'method_instapay')


class PaymentTrackingReportTests(TestCase):
    """The /manage/payment-tracking/ report: people-based funnel, ledger-based money."""

    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            username='root_bo', email='root@example.com', password=None
        )
        self.client = Client()
        self.client.defaults['HTTP_USER_AGENT'] = UA
        self.client.force_login(self.admin)
        self.monthly = Subscription.objects.create(name='Monthly', duration=30, days=30)
        self.annual = Subscription.objects.create(name='Annual', duration=365, days=365)

    def _user(self, name):
        return CustomUser.objects.create_user(username=name, email=f'{name}@example.com', password=None)

    def _event(self, page, event_type='page_view', action='', plan_type='', user=None,
               session_id='pvid_x', days_ago=0):
        event = PaymentTrackingEvent.objects.create(
            user=user, session_id=session_id, event_type=event_type,
            page=page, action=action, plan_type=plan_type,
        )
        if days_ago:
            PaymentTrackingEvent.objects.filter(pk=event.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago))
        return event

    def _pay(self, user, sub=None, amount='99.00', status='paid', key='', days_ago=0):
        payment = UserPayment.objects.create(
            user=user, subscription=sub or self.monthly, amount=amount, status=status,
            fawaterk_intent_key=key or None,
        )
        if days_ago:
            UserPayment.objects.filter(pk=payment.pk).update(date=timezone.now() - timedelta(days=days_ago))
        return payment

    def _report(self, query=''):
        response = self.client.get(reverse('manage_payment_tracking') + query)
        self.assertEqual(response.status_code, 200)
        return response.context

    def _counts(self, ctx):
        return [s['count'] for s in ctx['steps']]

    def test_funnel_counts_people_not_page_loads(self):
        for _ in range(4):
            self._event('payment', session_id='pvid_a')
        self._event('payment', session_id='pvid_b')
        self.assertEqual(self._counts(self._report()), [2, 0, 0, 0])

    def test_steps_are_cumulative(self):
        # opened checkout without a tracked plan click: still counts as having picked a plan
        self._event('payment', session_id='pvid_a')
        self._event('payment', 'click', 'plan_annual', 'pro_annual', session_id='pvid_b')
        self._event('payment', session_id='pvid_b')
        self._event('manual_payment', session_id='pvid_c')
        ctx = self._report()
        self.assertEqual(self._counts(ctx), [3, 2, 1, 0])
        first = ctx['steps'][0]
        self.assertEqual((first['lost'], first['lost_pct'], first['continue_pct']), (1, 33, 67))

    def test_guest_who_signs_in_is_one_person(self):
        user = self._user('merge_me')
        self._event('payment', session_id='pvid_m')
        self._event('manual_payment', user=user, session_id='pvid_m')
        ctx = self._report()
        self.assertEqual(ctx['steps'][0]['count'], 1)
        self.assertEqual({r['label']: r['visitors'] for r in ctx['segments']}.get('Signed in'), 1)

    def test_success_page_view_alone_is_not_a_sale(self):
        user = self._user('refresher')
        self._event('payment', user=user, session_id='pvid_r')
        self._event('payment_success', user=user, session_id='pvid_r')
        self._event('payment_success', user=user, session_id='pvid_r')
        ctx = self._report()
        self.assertEqual(ctx['steps'][-1]['count'], 0)
        self.assertEqual(ctx['revenue_total'], 0)

    def test_confirmed_payment_after_visit_is_a_conversion(self):
        user = self._user('buyer')
        self._event('payment', user=user, session_id='pvid_b')
        self._event('payment', 'click', 'plan_monthly', 'monthly', user=user, session_id='pvid_b')
        self._event('manual_payment', user=user, session_id='pvid_b')
        self._pay(user, key='MANUAL-ABCDEF123456')
        ctx = self._report()
        self.assertEqual(self._counts(ctx), [1, 1, 1, 1])
        self.assertEqual(ctx['conversion'], 100.0)

    def test_payment_before_the_visit_is_not_a_conversion(self):
        payer = self._user('early_payer')
        self._pay(payer, days_ago=10)
        self._event('payment', user=payer, session_id='pvid_e')
        ctx = self._report()
        self.assertEqual(ctx['steps'][-1]['count'], 0)
        self.assertEqual(ctx['renewal_visitors'], 1)
        self.assertEqual(ctx['untracked_subs'], 1)

    def test_revenue_comes_from_paid_payments_only(self):
        user = self._user('ledger')
        self._pay(user, amount='99.00', key='MANUAL-AAAAAAAAAAAA')
        self._pay(user, self.annual, amount='449.00', key='FW-INTENT-1')
        self._pay(user, amount='99.00', status='pending', key='FW-INTENT-2')
        self._pay(user, amount='99.00', status='failed', key='FW-INTENT-3')
        self._pay(user, amount='0', key='MANUAL-COUPON-XYZ')
        ctx = self._report()
        self.assertEqual(ctx['revenue_total'], 548)
        kpis = {k['key']: k for k in ctx['kpis']}
        self.assertEqual(kpis['revenue']['value'], '548')
        self.assertEqual(kpis['subs']['value'], '3')
        self.assertIn('1 free', kpis['subs']['sub'])
        self.assertEqual(kpis['aov']['value'], '274')
        methods = {r['key']: r['count'] for r in ctx['method_rows']}
        self.assertEqual(methods, {'card': 1, 'wallet': 1, 'coupon': 1})
        plans = {r['key']: r['subscriptions'] for r in ctx['plan_rows']}
        self.assertEqual(plans, {'monthly': 2, 'annual': 1})

    def test_new_vs_renewal(self):
        returning = self._user('returning')
        self._pay(returning, days_ago=60)
        self._pay(returning)
        self._pay(self._user('fresh'))
        kpis = {k['key']: k for k in self._report()['kpis']}
        self.assertIn('1 new · 1 renewal', kpis['subs']['sub'])

    def test_team_accounts_are_left_out_by_default(self):
        self._event('payment', user=self.admin, session_id='pvid_admin')
        self._event('payment', session_id='pvid_admin')  # admin's guest-phase event
        self._pay(self.admin)
        self._event('payment', session_id='pvid_real')
        ctx = self._report()
        self.assertEqual(ctx['steps'][0]['count'], 1)
        self.assertEqual(ctx['revenue_total'], 0)
        ctx = self._report('?team=1')
        self.assertEqual(ctx['steps'][0]['count'], 2)
        self.assertEqual(ctx['revenue_total'], 99)

    def test_leads_are_unpaid_signed_in_people_who_went_past_pricing(self):
        hot = self._user('hot_lead')
        warm = self._user('warm_lead')
        browsing = self._user('just_browsing')
        payer = self._user('already_paying')
        self._event('manual_payment', user=hot, session_id='pvid_h')
        self._event('payment', 'click', 'plan_annual', 'pro_annual', user=warm, session_id='pvid_w')
        self._event('payment', user=browsing, session_id='pvid_br')
        self._pay(payer, days_ago=40, sub=self.annual)
        self._event('fawaterk_checkout', user=payer, session_id='pvid_p')
        self._event('manual_payment', session_id='pvid_guest')
        leads = self._report()['leads']
        self.assertEqual([r['username'] for r in leads], ['hot_lead', 'warm_lead'])
        self.assertEqual(leads[1]['plan'], 'Annual')

    def test_card_checkout_health(self):
        user = self._user('carder')
        self._pay(user, key='FW-1')
        self._pay(user, status='failed', key='FW-2')
        stale = self._pay(user, status='pending', key='FW-3')
        UserPayment.objects.filter(pk=stale.pk).update(date=timezone.now() - timedelta(hours=3))
        self._pay(user, status='pending', key='FW-4')  # still inside the grace window
        health = self._report()['health']
        self.assertEqual((health['card_started'], health['card_paid'], health['card_failed'],
                          health['card_abandoned']), (4, 1, 1, 1))
        self.assertEqual(health['card_success_pct'], 33.3)

    def test_deltas_compare_with_the_previous_period(self):
        user = self._user('trend')
        self._pay(user, amount='100.00', days_ago=40)
        self._pay(user, amount='150.00', days_ago=2)
        kpis = {k['key']: k for k in self._report('?days=30')['kpis']}
        self.assertEqual(kpis['revenue']['delta']['label'], '+50%')
        self.assertIsNone({k['key']: k for k in self._report('?days=all')['kpis']}['revenue']['delta'])

    def test_period_filter(self):
        self._event('payment', session_id='pvid_old', days_ago=20)
        self._event('payment', session_id='pvid_new')
        self.assertEqual(self._report('?days=7')['steps'][0]['count'], 1)
        self.assertEqual(self._report('?days=30')['steps'][0]['count'], 2)
        self.assertEqual(self._report('?days=bogus')['days'], '30')

    def test_insights_flag_the_review_queue(self):
        from core.models import ManualPayment
        user = self._user('receipt')
        ManualPayment.objects.create(user=user, plan_type='monthly', amount_expected='99.00',
                                     sender_identifier='0100', receipt_image='receipts/x.jpg',
                                     status='needs_review')
        ctx = self._report()
        titles = [i['title'] for i in ctx['insights']]
        self.assertIn('1 payment receipt waiting for review', titles)
        self.assertContains(self.client.get(reverse('manage_payment_tracking')), 'status__exact=needs_review')

    def test_page_renders_every_period(self):
        user = self._user('render')
        self._event('payment', user=user, session_id='pvid_q')
        self._event('payment', 'click', 'plan_monthly', 'monthly', user=user, session_id='pvid_q')
        self._pay(user, days_ago=100)
        self._pay(user)
        for days in ('7', '30', '90', 'all'):
            response = self.client.get(reverse('manage_payment_tracking') + f'?days={days}')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Where buyers drop out')
            self.assertContains(response, 'prTrendData')

    def test_handles_an_empty_period(self):
        ctx = self._report('?days=7')
        self.assertFalse(ctx['has_data'])

    def test_csv_exports(self):
        lead = self._user('csv_lead')
        self._event('manual_payment', user=lead, session_id='pvid_c')
        self._pay(self._user('csv_payer'), key='MANUAL-BBBBBBBBBBBB')
        for kind, expect in (('leads', 'csv_lead'), ('payments', 'csv_payer'), ('events', 'Manual payment')):
            response = self.client.get(reverse('manage_payment_tracking') + f'?export={kind}')
            self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
            body = response.content.decode('utf-8')
            self.assertTrue(body.startswith('\ufeff'))
            self.assertIn(expect, body)

    def test_requires_superuser(self):
        self.client.force_login(self._user('nosy'))
        response = self.client.get(reverse('manage_payment_tracking'))
        self.assertEqual(response.status_code, 302)


class SubscriptionStackingTests(TestCase):
    """Paying while a plan is still running adds the new days on top of it."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(username='stacker', email='stacker@example.com')
        self.monthly = Subscription.objects.create(name='Monthly', duration=30, days=30)
        self.annual = Subscription.objects.create(name='Annual', duration=365, days=365)

    def _paid(self, sub, days_ago=0, **extra):
        payment = UserPayment.objects.create(user=self.user, subscription=sub, status='paid', **extra)
        if days_ago:
            UserPayment.objects.filter(pk=payment.pk).update(date=timezone.now() - timedelta(days=days_ago))
            payment.refresh_from_db()
        return payment

    def _days_left(self, payment):
        return (payment.expiration_date - timezone.now()).days

    def test_first_payment_carries_nothing(self):
        payment = self._paid(self.monthly)
        self.assertIsNone(payment.carried_over)
        self.assertEqual(self._days_left(payment), 29)

    def test_renewing_early_adds_the_remaining_days(self):
        self._paid(self.monthly, days_ago=10)  # 20 days left
        renewal = self._paid(self.monthly)
        self.assertEqual(renewal.carried_over.days, 19)  # 19 days + some hours
        self.assertEqual(self._days_left(renewal), 49)
        self.assertEqual(renewal.total_days, 49)
        self.assertTrue(renewal.is_active)

    def test_upgrading_to_annual_keeps_the_monthly_days(self):
        self._paid(self.monthly, days_ago=5)  # 25 days left
        upgrade = self._paid(self.annual)
        self.assertEqual(self._days_left(upgrade), 365 + 24)

    def test_renewing_after_expiry_starts_fresh(self):
        self._paid(self.monthly, days_ago=40)
        renewal = self._paid(self.monthly)
        self.assertIsNone(renewal.carried_over)
        self.assertEqual(self._days_left(renewal), 29)

    def test_three_stacked_payments_chain(self):
        self._paid(self.monthly)
        self._paid(self.monthly)
        third = self._paid(self.monthly)
        self.assertEqual(self._days_left(third), 89)

    def test_pending_payment_stacks_when_it_flips_to_paid(self):
        self._paid(self.monthly, days_ago=10)
        pending = UserPayment.objects.create(
            user=self.user, subscription=self.monthly, status='pending', fawaterk_intent_key='INTENT-1'
        )
        self.assertIsNone(pending.carried_over)
        from payments.views import _activate_subscription_by_intent
        _activate_subscription_by_intent('INTENT-1', self.user)
        pending.refresh_from_db()
        self.assertEqual(self._days_left(pending), 49)
        self.assertTrue(self.user.has_active_subscription)

    def test_resaving_a_paid_payment_does_not_stack_again(self):
        self._paid(self.monthly, days_ago=10)
        renewal = self._paid(self.monthly)
        carried = renewal.carried_over
        renewal.amount = 50
        renewal.save()
        renewal.refresh_from_db()
        self.assertEqual(renewal.carried_over, carried)

    def test_other_users_plans_are_ignored(self):
        other = CustomUser.objects.create_user(username='other', email='other@example.com')
        UserPayment.objects.create(user=other, subscription=self.annual, status='paid')
        payment = self._paid(self.monthly)
        self.assertIsNone(payment.carried_over)

    def test_dashboard_shows_the_stacked_window(self):
        self._paid(self.monthly, days_ago=10)
        self._paid(self.monthly)
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['days_left'], 49)
        self.assertEqual(response.context['subscription_days'], 49)
        self.assertEqual(response.context['plan_name'], 'Monthly Pro')
