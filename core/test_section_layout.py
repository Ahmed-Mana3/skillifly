"""Tests for the portfolio section-layout feature (order + visibility)."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Category, Profile, Theme
from core.section_order import (
    normalize_section_order,
    normalize_section_visibility,
    resolve_section_layout,
)

User = get_user_model()


class SectionOrderNormalizationTests(TestCase):
    def test_drops_unknown_and_duplicates(self):
        result = normalize_section_order(
            ['skills', 'bogus', 'skills', 'projects'], 'video_editor'
        )
        self.assertEqual(result[0:2], ['skills', 'projects'])

    def test_appends_missing_supported_keys(self):
        result = normalize_section_order(['links'], 'video_editor')
        self.assertIn('links', result)
        self.assertEqual(len(result), len(set(result)))
        # every supported key stays reachable
        from core.section_order import supported_keys
        for key in supported_keys('video_editor'):
            self.assertIn(key, result)

    def test_accepts_comma_string(self):
        result = normalize_section_order('education, projects', 'student')
        self.assertEqual(result[0], 'education')
        self.assertEqual(result[1], 'projects')

    def test_empty_falls_back_to_category_default(self):
        self.assertEqual(
            normalize_section_order('', 'student'),
            ['education', 'skills', 'experience', 'projects', 'links'],
        )

    def test_filters_keys_unsupported_for_category(self):
        # reviews/creators/contact are video_editor-only
        result = normalize_section_order(['reviews', 'skills'], 'developer')
        self.assertNotIn('reviews', result)
        self.assertIn('skills', result)


class SectionVisibilityNormalizationTests(TestCase):
    def test_dict_input_coerces_bools(self):
        result = normalize_section_visibility({'skills': 0, 'links': 'yes'}, 'video_editor')
        self.assertEqual(result, {'skills': False, 'links': True})

    def test_json_string_input(self):
        result = normalize_section_visibility(json.dumps({'projects': False}), 'video_editor')
        self.assertEqual(result, {'projects': False})

    def test_unknown_keys_dropped(self):
        result = normalize_section_visibility({'nope': False, 'skills': False}, 'video_editor')
        self.assertEqual(result, {'skills': False})

    def test_garbage_string_returns_empty(self):
        self.assertEqual(normalize_section_visibility('not-json{', 'video_editor'), {})


class ResolveSectionLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='layouter', email='l@example.com', password='x')
        self.profile = Profile.objects.create(user=self.user)

    def test_no_saved_layout_is_not_custom(self):
        layout = resolve_section_layout(self.profile, 'video_editor')
        self.assertFalse(layout['custom'])
        self.assertEqual(layout['hidden_keys'], [])
        # Resolved keys mirror the theme default so the builder panel can
        # display them; templates only emit CSS when custom is True.
        self.assertEqual(
            layout['order_keys'],
            ['projects', 'skills', 'experience', 'reviews', 'creators', 'education', 'links', 'contact'],
        )
        self.assertEqual(layout['default_order'], layout['order_keys'])

    def test_saved_order_resolves_custom(self):
        self.profile.section_order = ['skills', 'projects']
        self.profile.save()
        layout = resolve_section_layout(self.profile, 'video_editor')
        self.assertTrue(layout['custom'])
        self.assertEqual(layout['order_keys'][0], 'skills')
        self.assertEqual(layout['order_keys'][1], 'projects')

    def test_hidden_keys_reported(self):
        self.profile.section_order = ['projects', 'skills']
        self.profile.section_visibility = {'skills': False}
        self.profile.save()
        layout = resolve_section_layout(self.profile, 'video_editor')
        self.assertTrue(layout['custom'])
        self.assertEqual(layout['hidden_keys'], ['skills'])
        by_key = {s['key']: s for s in layout['sections']}
        self.assertFalse(by_key['skills']['visible'])
        self.assertTrue(by_key['projects']['visible'])
        # selectors + hrefs exposed for the template CSS block
        self.assertIn('#skills', by_key['skills']['selectors'])
        self.assertIn('skills', by_key['skills']['hrefs'])

    def test_none_profile_safe(self):
        layout = resolve_section_layout(None, 'video_editor')
        self.assertFalse(layout['custom'])


class AjaxSaveSectionLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='saver', email='s@example.com', password='x')
        self.client.login(username='saver', password='x')
        category = Category.objects.create(name='Video Editor')
        theme = Theme.objects.create(name='Minimal', category=category)
        self.profile = Profile.objects.create(user=self.user, theme=theme)
        self.url = reverse('ajax_save_section_layout')

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url, {'section_order': '["skills"]'})
        self.assertEqual(response.status_code, 302)

    def test_valid_save_persists_both_fields_atomically(self):
        response = self.client.post(self.url, {
            'section_order': json.dumps(['skills', 'projects']),
            'section_visibility': json.dumps({'experience': False}),
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.section_order[0], 'skills')
        self.assertEqual(self.profile.section_order[1], 'projects')
        self.assertFalse(self.profile.section_visibility.get('experience', True))

    def test_unknown_key_rejected_with_400(self):
        response = self.client.post(self.url, {
            'section_order': json.dumps(['skills', 'hax0r']),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid_keys', response.json())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.section_order, [])

    def test_unknown_visibility_key_rejected(self):
        response = self.client.post(self.url, {
            'section_order': json.dumps(['skills']),
            'section_visibility': json.dumps({'nope': False}),
        })
        self.assertEqual(response.status_code, 400)

    def test_cannot_hide_every_section(self):
        keys = ['projects', 'skills', 'experience', 'reviews', 'creators', 'education', 'links', 'contact']
        response = self.client.post(self.url, {
            'section_order': json.dumps(keys),
            'section_visibility': json.dumps({key: False for key in keys}),
        })
        self.assertEqual(response.status_code, 400)

    def test_reset_clears_to_theme_default(self):
        self.profile.section_order = ['skills']
        self.profile.save()
        response = self.client.post(self.url, {'reset': '1'})
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.section_order, [])
        self.assertEqual(self.profile.section_visibility, {})
        self.assertTrue(response.json()['reset'])

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)


class BuilderSectionPanelContextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='paneluser', email='p@example.com', password='x')
        self.client.login(username='paneluser', password='x')
        category = Category.objects.create(name='Video Editor')
        theme = Theme.objects.create(name='Minimal', category=category)
        Profile.objects.create(user=self.user, theme=theme)

    def _builder_response(self):
        return self.client.get(reverse('builder'))

    def test_panel_rows_follow_saved_order_and_visibility(self):
        profile = self.user.profile
        profile.section_order = ['skills', 'projects']
        profile.section_visibility = {'projects': False}
        profile.save()

        response = self._builder_response()
        self.assertEqual(response.status_code, 200)
        rows = response.context['section_rows']
        self.assertEqual([row['key'] for row in rows][0:2], ['skills', 'projects'])
        self.assertFalse(rows[1]['visible'])

        hidden_input = response.context['section_visibility_json']
        self.assertIn('projects', hidden_input)

    def test_default_context_when_nothing_saved(self):
        response = self._builder_response()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_custom_layout'])
        self.assertTrue(response.context['default_section_order'])


class PreviewViewSectionLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='previewer', email='pv@example.com', password='x')
        category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Minimal', category=category)
        Profile.objects.create(user=self.user, theme=self.theme, is_public=True)
        self.client.login(username='previewer', password='x')

    def _preview(self):
        return self.client.get(reverse('preview', kwargs={'username': self.user.username}))

    def test_preview_without_layout_emits_no_css(self):
        response = self._preview()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('.portfolio-body { display: flex', content)
        self.assertFalse(response.context['section_layout']['custom'])

    def test_preview_renders_order_and_hide_rules(self):
        profile = self.user.profile
        profile.section_order = ['skills', 'projects']
        profile.section_visibility = {'education': False}
        profile.save()

        response = self._preview()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # skills ordered before projects
        self.assertLess(content.index('#skills { order: 1;'), content.index('#portfolio { order: 2;'))
        # education hidden with dead-anchor cleanup
        self.assertIn('#education { display: none !important; }', content)
        self.assertIn('a[href="#education"] { display: none !important; }', content)
