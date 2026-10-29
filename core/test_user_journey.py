"""User lookup (/manage/users/) and one user's journey (/manage/users/<id>/)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import user_journey as uj
from core.models import (
    ActivationEvent, AgentConversation, AgentMessage, AnalyticsVisit, CustomDomain, ManualPayment, NudgeLog,
    PaymentTrackingEvent, PersonalInfo, Profile, Project, UserPayment,
)
from core.testing_helpers import give_payment, make_editor

NOW = timezone.now


def seen(user, **ago):
    Profile.objects.update_or_create(user=user, defaults={'last_seen': NOW() - timedelta(**ago)})


def backdate(obj, field='created_at', **ago):
    type(obj).objects.filter(pk=obj.pk).update(**{field: NOW() - timedelta(**ago)})


class UserJourneyTests(TestCase):
    def setUp(self):
        self.admin = make_editor('boss', is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def journey(self, user):
        return uj.build_journey(user)

    def titles(self, journey, cat=''):
        return [r['title'] for r in uj.timeline(journey['events'], cat)]

    # ── Access ─────────────────────────────────────────────────────────────

    def test_superusers_only(self):
        user = make_editor('plain')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('manage_user_lookup')).status_code, 302)
        self.assertEqual(self.client.get(reverse('manage_user_journey', args=[user.pk])).status_code, 302)

    def test_unknown_user_is_404(self):
        self.assertEqual(self.client.get(reverse('manage_user_journey', args=[99999])).status_code, 404)

    def test_manage_hub_links_to_lookup(self):
        self.assertContains(self.client.get(reverse('manage_dashboard')), reverse('manage_user_lookup'))

    # ── Lookup ─────────────────────────────────────────────────────────────

    def test_empty_search_lists_recent_people(self):
        sara = make_editor('sara_k')
        seen(sara, hours=1)
        response = self.client.get(reverse('manage_user_lookup'))
        self.assertContains(response, 'Recently active')
        self.assertContains(response, reverse('manage_user_journey', args=[sara.pk]))

    def test_search_matches_many_fields_and_lists_them(self):
        a = make_editor('omar_edits')
        b = make_editor('omar_cuts')
        response = self.client.get(reverse('manage_user_lookup'), {'q': 'omar'})
        self.assertContains(response, reverse('manage_user_journey', args=[a.pk]))
        self.assertContains(response, reverse('manage_user_journey', args=[b.pk]))

        PersonalInfo.objects.create(user=a, full_name='Omar Hany', title='Editor', email='x@y.z',
                                    phone='01012345678', bio='')
        CustomDomain.objects.create(user=b, domain='omarcuts.com')
        self.assertEqual([r['id'] for r in uj.search_users('0101234')], [a.pk])
        self.assertEqual([r['id'] for r in uj.search_users('omarcuts.com')], [b.pk])
        self.assertEqual([r['id'] for r in uj.search_users(str(b.pk))][0], b.pk)

    def test_single_match_opens_the_journey(self):
        user = make_editor('unique_person')
        response = self.client.get(reverse('manage_user_lookup'), {'q': '@unique_person'})
        self.assertRedirects(response, reverse('manage_user_journey', args=[user.pk]))

    def test_no_match(self):
        self.assertContains(self.client.get(reverse('manage_user_lookup'), {'q': 'zzz-nobody'}), 'Nobody matches')

    # ── Timeline sources ───────────────────────────────────────────────────

    def test_timeline_gathers_every_source(self):
        user = make_editor('rich', days_old=10)
        ActivationEvent.objects.create(user=user, name='signup_completed',
                                       props={'method': 'google', 'lang': 'ar', 'source': 'instagram'})
        ActivationEvent.objects.create(user=user, name='theme_switched', props={'from': 'Pro', 'to': 'Creative'})
        Project.objects.create(user=user, title='Wedding film')
        PaymentTrackingEvent.objects.create(user=user, session_id='s1', page='payment')
        PaymentTrackingEvent.objects.create(user=None, session_id='s1', event_type='click', page='payment',
                                            action='plan_monthly', plan_type='monthly')
        give_payment(user, days_ago=2)
        NudgeLog.objects.create(user=user, key='no_project_24h')
        conv = AgentConversation.objects.create(user=user, title='Bio help')
        AgentMessage.objects.create(conversation=conv, sender='user', text='Write my bio please')
        AnalyticsVisit.objects.create(user=user, session_id='v1', country='Egypt', user_agent='Mozilla')
        AnalyticsVisit.objects.create(user=user, session_id='v2', user_agent='Googlebot/2.1')

        j = self.journey(user)
        titles = self.titles(j)
        signup = next(r for r in j['events'] if r['title'] == 'Signed up')
        self.assertIn('with Google', signup['detail'])
        self.assertIn('from instagram', signup['detail'])
        self.assertIn('Switched theme to Creative', titles)
        self.assertIn('Added a video: “Wedding film”', titles)
        self.assertIn('Opened the pricing page', titles)
        clicked = next(r for r in j['events'] if r['title'] == 'Clicked “Get monthly plan”')
        self.assertIn('Before signing in', clicked['detail'])
        self.assertIn('Paid 99 EGP for the monthly plan', titles)
        self.assertIn('We sent a nudge email', titles)
        self.assertIn('Asked the AI assistant', titles)
        self.assertIn('Portfolio got 1 visit', titles)  # the bot visit is left out
        self.assertEqual({r['cat'] for r in j['events']},
                         {'account', 'portfolio', 'payments', 'emails', 'ai', 'traction'})

    def test_deleted_video_still_shows(self):
        user = make_editor('deleter')
        ActivationEvent.objects.create(user=user, name='project_created', props={'provider': 'youtube'})
        self.assertIn('Added a video (since deleted)', self.titles(self.journey(user)))

    def test_back_to_back_repeats_fold_into_one_row(self):
        user = make_editor('repeat')
        for _ in range(3):
            ActivationEvent.objects.create(user=user, name='dashboard_viewed', props={})
        rows = [r for r in uj.timeline(self.journey(user)['events']) if r['title'] == 'Opened the dashboard']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['count'], 3)
        hidden = uj.timeline(self.journey(user)['events'], show_minor=False)
        self.assertNotIn('Opened the dashboard', [r['title'] for r in hidden])

    # ── Verdict ────────────────────────────────────────────────────────────

    def test_paying_but_quiet_is_at_risk(self):
        user = make_editor('quiet_pay', days_old=60)
        give_payment(user, days_ago=20, plan_days=365)
        seen(user, days=20)
        User = type(user)
        User.objects.filter(pk=user.pk).update(last_login=NOW() - timedelta(days=20))
        user.refresh_from_db()
        j = self.journey(user)
        self.assertEqual(j['segment']['key'], 'at_risk')
        self.assertTrue(any(a['href'].startswith('mailto:') for a in j['actions']))

    def test_unfinished_checkout_is_abandoned(self):
        user = make_editor('almost', days_old=5)
        seen(user, hours=3)
        UserPayment.objects.create(user=user, amount=99, status='pending', fawaterk_intent_key='fw-1')
        j = self.journey(user)
        self.assertEqual(j['segment']['key'], 'abandoned')
        self.assertTrue(j['facts']['checkout_open'])

    def test_active_free_user_with_videos_is_ready_to_upgrade(self):
        user = make_editor('builder', days_old=4)
        seen(user, hours=2)
        Project.objects.create(user=user, title='Reel')
        self.assertEqual(self.journey(user)['segment']['key'], 'upgrade')

    def test_no_video_after_days_is_stalled_and_milestone_shows_where(self):
        user = make_editor('stuck', days_old=6)
        seen(user, hours=5)
        j = self.journey(user)
        self.assertEqual(j['segment']['key'], 'stalled')
        nxt = next(m for m in j['milestones'] if m['is_next'])
        self.assertEqual(nxt['key'], 'verified')

    def test_stuck_marker_sits_after_the_furthest_step(self):
        user = make_editor('paid_unverified', days_old=10)
        Project.objects.create(user=user, title='Cut')
        give_payment(user)
        stuck = [m['key'] for m in self.journey(user)['milestones'] if m['is_next']]
        self.assertEqual(stuck, [])  # paid is the last real step; a missing email verification is not "stopped here"

    def test_expired_recently_is_winback(self):
        user = make_editor('lapsed', days_old=90)
        give_payment(user, days_ago=40)
        self.assertEqual(self.journey(user)['segment']['key'], 'winback')

    def test_receipt_waiting_for_review_is_the_first_action(self):
        user = make_editor('receipt')
        receipt = ManualPayment.objects.create(user=user, plan_type='monthly', amount_expected=99,
                                               sender_identifier='0100', receipt_image='r.png',
                                               status='needs_review')
        first = self.journey(user)['actions'][0]
        self.assertEqual(first['title'], 'Review their payment receipt')
        self.assertIn(str(receipt.pk), first['href'])

    def test_health_score_is_bounded_and_explained(self):
        user = make_editor('scored')
        health = self.journey(user)['health']
        self.assertTrue(0 <= health['score'] <= 100)
        self.assertEqual(sum(p['max'] for p in health['parts']), 100)

    # ── Page ───────────────────────────────────────────────────────────────

    def test_page_renders_filters_and_exports(self):
        user = make_editor('page_user', days_old=3)
        Project.objects.create(user=user, title='Ad cut')
        give_payment(user)
        url = reverse('manage_user_journey', args=[user.pk])

        response = self.client.get(url)
        self.assertContains(response, 'Verdict')
        self.assertContains(response, 'Health score')
        self.assertContains(response, 'Added a video: “Ad cut”')

        filtered = self.client.get(url, {'cat': 'payments'})
        self.assertContains(filtered, 'Paid 99 EGP')
        self.assertNotContains(filtered, 'Added a video: “Ad cut”')

        csv = self.client.get(url, {'export': 'csv'})
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')
        body = csv.content.decode('utf-8-sig')
        self.assertIn('Time,Area,Action,Detail,Times', body)
        self.assertIn('Ad cut', body)

    def test_routine_actions_are_hidden_until_asked_for(self):
        user = make_editor('routine')
        ActivationEvent.objects.create(user=user, name='dashboard_viewed', props={})
        url = reverse('manage_user_journey', args=[user.pk])
        self.assertNotContains(self.client.get(url), 'Opened the dashboard')
        self.assertContains(self.client.get(url, {'minor': '1'}), 'Opened the dashboard')

    def test_calendar_labels_each_month_once(self):
        cal = uj._calendar([], None, NOW())
        labels = [w['label'] for w in cal['weeks'] if w['label']]
        self.assertEqual(len(labels), len(set(labels)))

    def test_page_works_for_a_bare_account(self):
        user = make_editor('bare', account_type=None)
        response = self.client.get(reverse('manage_user_journey', args=[user.pk]))
        self.assertContains(response, 'Signed up')
