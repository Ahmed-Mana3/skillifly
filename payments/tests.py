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
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            username='root_bo', email='root@example.com', password='Password123!'
        )
        self.client = Client()
        self.client.defaults['HTTP_USER_AGENT'] = UA
        self.client.force_login(self.admin)

    def _event(self, page, event_type='page_view', action='', plan_type='', user=None, session_id='pvid_x'):
        return PaymentTrackingEvent.objects.create(
            user=user, session_id=session_id, event_type=event_type,
            page=page, action=action, plan_type=plan_type,
        )

    def test_report_ranks_pages_in_funnel_order(self):
        # volume order would be the reverse of the real flow
        self._event('payment_success', session_id='pvid_a')
        self._event('fawaterk_checkout', session_id='pvid_b')
        self._event('payment', session_id='pvid_c')
        response = self.client.get(reverse('manage_payment_tracking'))
        self.assertEqual(response.status_code, 200)
        pages = [row['page'] for row in response.context['page_rows']]
        self.assertEqual(pages, ['payment', 'fawaterk_checkout', 'payment_success'])

    def test_report_continue_percentage(self):
        for _ in range(4):
            self._event('payment', session_id='pvid_a')
        self._event('fawaterk_checkout', session_id='pvid_b')
        response = self.client.get(reverse('manage_payment_tracking'))
        rows = {row['page']: row for row in response.context['page_rows']}
        self.assertEqual(rows['payment']['continue_pct'], 25)
        self.assertEqual(rows['payment']['next_label'], 'Fawaterk checkout')
        self.assertIsNone(rows['fawaterk_checkout']['continue_pct'])

    def test_report_merges_opens_and_clicks_per_visitor(self):
        self._event('payment', session_id='pvid_a')
        self._event('payment', event_type='click', action='plan_monthly', session_id='pvid_a')
        response = self.client.get(reverse('manage_payment_tracking'))
        self.assertEqual(response.context['unique_visitors'], 1)
        guest = [r for r in response.context['user_rows'] if r['kind'] == 'guest']
        self.assertEqual(len(guest), 1)
        self.assertEqual((guest[0]['views'], guest[0]['clicks']), (1, 1))

    def test_report_flags_users_who_already_pay(self):
        payer = CustomUser.objects.create_user(
            username='payer_bo', email='payer@example.com', password='Password123!'
        )
        lapsed = CustomUser.objects.create_user(
            username='lapsed_bo', email='lapsed@example.com', password='Password123!'
        )
        sub = Subscription.objects.create(name='Pro', duration=30, days=30)
        UserPayment.objects.create(user=payer, subscription=sub, status='paid')
        old = Subscription.objects.create(name='Old', duration=30, days=30)
        stale = UserPayment.objects.create(user=lapsed, subscription=old, status='paid')
        UserPayment.objects.filter(pk=stale.pk).update(
            date=timezone.now() - timedelta(days=90)
        )

        self._event('payment', user=payer, session_id='pvid_p')
        self._event('payment', user=lapsed, session_id='pvid_l')

        response = self.client.get(reverse('manage_payment_tracking'))
        self.assertEqual(response.context['paying_users'], 1)
        by_identity = {r['identity']: r for r in response.context['user_rows']}
        self.assertTrue(by_identity['payer_bo']['is_paying'])
        self.assertFalse(by_identity['lapsed_bo']['is_paying'])

    def test_report_handles_an_empty_period(self):
        response = self.client.get(reverse('manage_payment_tracking') + '?days=7')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_data'])
