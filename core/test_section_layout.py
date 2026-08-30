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
    supported_keys,
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

    def test_display_name_category_equivalent_to_slug(self):
        # DB stores the category label ("Video Editor"); the canonical slug is
        # "video_editor". Both spellings (plus dashes/whitespace) must behave
        # identically, not only for the video-editor fallback.
        order = normalize_section_order('reviews, skills', 'Video Editor')
        self.assertEqual(order[0], 'reviews')
        self.assertEqual(order, normalize_section_order('reviews, skills', 'video_editor'))
        from core.section_order import supported_keys
        self.assertEqual(supported_keys('Student'), supported_keys('student'))

    def test_developer_slug_variants(self):
        from core.section_order import supported_keys
        self.assertEqual(supported_keys('Developer'), ['projects', 'skills', 'experience', 'education', 'links'])

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
        # Resolved keys mirror the theme default (the creative theme's
        # sequence) so the builder panel can display them; templates only
        # emit CSS when custom is True.
        self.assertEqual(
            layout['order_keys'],
            ['projects', 'skills', 'experience', 'education', 'creators', 'reviews', 'links', 'contact'],
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

    def test_display_name_category_resolves_identically(self):
        # resolve_section_layout must normalize the raw category label the same
        # way the builder does, so a saved layout renders on the public page.
        self.profile.section_order = ['reviews', 'projects']
        self.profile.save()
        for label in ('Video Editor', 'video editor', 'video_editor', '  video-editor  '):
            layout = resolve_section_layout(self.profile, label)
            self.assertTrue(layout['custom'], label)
            self.assertEqual(layout['order_keys'][0], 'reviews', label)
            self.assertEqual(len(layout['order_keys']), len(supported_keys('video_editor')), label)


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

    def test_default_equal_save_stores_no_custom_layout(self):
        keys = ['projects', 'skills', 'experience', 'education', 'creators', 'reviews', 'links', 'contact']
        response = self.client.post(self.url, {
            'section_order': json.dumps(keys),
            'section_visibility': json.dumps({key: True for key in keys}),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.section_order, [])
        self.assertEqual(self.profile.section_visibility, {})
        self.assertFalse(resolve_section_layout(self.profile, 'video_editor')['custom'])

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
        # flex children keep their full width despite `margin: 0 auto`
        self.assertIn('.portfolio-body > * { width: 100%; }', content)


class CategoriesThemeLayoutTests(TestCase):
    """The categories theme has its own DOM order and section set.

    It renders no dedicated links section (social links live inside its
    contact section), so 'links' must never appear in its panel rows and its
    "theme default" equals its own hard-coded DOM order, not the family's.
    """

    CATEGORIES_ORDER = ['projects', 'creators', 'skills', 'experience', 'education', 'reviews', 'contact']

    def setUp(self):
        self.user = User.objects.create_user(username='catuser', email='cat@example.com', password='x')
        category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Categories', category=category)

    def _login_with_theme(self, **profile_kwargs):
        profile = Profile.objects.create(user=self.user, theme=self.theme, **profile_kwargs)
        self.client.login(username='catuser', password='x')
        return profile

    def test_supported_keys_match_theme_dom_order(self):
        self.assertEqual(supported_keys('video_editor', 'categories'), self.CATEGORIES_ORDER)

    def test_resolve_uses_theme_default_from_profile(self):
        profile = Profile.objects.create(user=self.user, theme=self.theme)
        layout = resolve_section_layout(profile, 'video_editor')
        self.assertFalse(layout['custom'])
        self.assertEqual(layout['order_keys'], self.CATEGORIES_ORDER)
        self.assertEqual(layout['default_order'], self.CATEGORIES_ORDER)

    def test_builder_panel_enabled_and_hides_links_row(self):
        self._login_with_theme()
        response = self.client.get(reverse('builder'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['section_layout_enabled'])
        row_keys = [row['key'] for row in response.context['section_rows']]
        self.assertEqual(row_keys, self.CATEGORIES_ORDER)

    def test_ajax_save_rejects_unsupported_links_key(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(['projects', 'links']),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid_keys', response.json())
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])

    def test_ajax_save_theme_default_stores_nothing(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(self.CATEGORIES_ORDER),
            'section_visibility': json.dumps({key: True for key in self.CATEGORIES_ORDER}),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])
        self.assertEqual(profile.section_visibility, {})
        self.assertFalse(resolve_section_layout(profile, 'video_editor')['custom'])

    def test_preview_custom_order_emits_theme_selectors(self):
        profile = self._login_with_theme(is_public=True)
        profile.section_order = ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact']
        profile.save()

        response = self.client.get(reverse('preview', kwargs={'username': self.user.username}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # creators moved ahead of the collections grid (#work)
        self.assertLess(content.index('#creators { order: 1;'), content.index('#work { order: 2;'))
        # no links rules — the theme has no #connect section
        self.assertNotIn('#connect', content)


class CreativeWhiteThemeLayoutTests(TestCase):
    """The creative_white theme has its own DOM order and section set.

    Its creators marquee opens the page right after the hero, and it renders
    no dedicated links section (social links live inside its contact
    section). Its decorative .marquee-strip ticker must never be touched by
    creators rules — only the real creators marquee is.
    """

    CREATIVE_WHITE_ORDER = ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact']

    def setUp(self):
        self.user = User.objects.create_user(username='whiteuser', email='white@example.com', password='x')
        category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Creative White', category=category)

    def _login_with_theme(self, **profile_kwargs):
        profile = Profile.objects.create(user=self.user, theme=self.theme, **profile_kwargs)
        self.client.login(username='whiteuser', password='x')
        return profile

    def test_supported_keys_match_theme_dom_order(self):
        self.assertEqual(supported_keys('video_editor', 'creative_white'), self.CREATIVE_WHITE_ORDER)

    def test_resolve_uses_theme_default_from_profile(self):
        profile = Profile.objects.create(user=self.user, theme=self.theme)
        layout = resolve_section_layout(profile, 'video_editor')
        self.assertFalse(layout['custom'])
        self.assertEqual(layout['order_keys'], self.CREATIVE_WHITE_ORDER)
        self.assertEqual(layout['default_order'], self.CREATIVE_WHITE_ORDER)

    def test_builder_panel_enabled_and_hides_links_row(self):
        self._login_with_theme()
        response = self.client.get(reverse('builder'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['section_layout_enabled'])
        row_keys = [row['key'] for row in response.context['section_rows']]
        self.assertEqual(row_keys, self.CREATIVE_WHITE_ORDER)

    def test_ajax_save_rejects_unsupported_links_key(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(['projects', 'links']),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid_keys', response.json())
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])

    def test_ajax_save_theme_default_stores_nothing(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(self.CREATIVE_WHITE_ORDER),
            'section_visibility': json.dumps({key: True for key in self.CREATIVE_WHITE_ORDER}),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])
        self.assertEqual(profile.section_visibility, {})
        self.assertFalse(resolve_section_layout(profile, 'video_editor')['custom'])

    def test_preview_hiding_creators_spares_decorative_marquee(self):
        profile = self._login_with_theme(is_public=True)
        profile.section_visibility = {'creators': False}
        profile.save()

        response = self.client.get(reverse('preview', kwargs={'username': self.user.username}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # the real creators section + its marquee are hidden
        self.assertIn('#creators { display: none !important; }', content)
        self.assertIn('.creators-marquee-container { display: none !important; }', content)
        # the hero's decorative .marquee-strip ticker is NOT part of creators
        self.assertNotIn('.marquee-strip { display: none', content)


class CreativeThemeLayoutTests(TestCase):
    """The creative theme follows the family's canonical sequence minus the
    links section — its social links render inside the contact section, so
    'links' never appears in its panel rows or its saved layouts.
    """

    CREATIVE_ORDER = ['projects', 'skills', 'experience', 'education', 'creators', 'reviews', 'contact']

    def setUp(self):
        self.user = User.objects.create_user(username='creativeuser', email='creative@example.com', password='x')
        category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Creative', category=category)

    def _login_with_theme(self, **profile_kwargs):
        profile = Profile.objects.create(user=self.user, theme=self.theme, **profile_kwargs)
        self.client.login(username='creativeuser', password='x')
        return profile

    def test_supported_keys_match_theme_dom_order(self):
        self.assertEqual(supported_keys('video_editor', 'creative'), self.CREATIVE_ORDER)

    def test_resolve_uses_theme_default_from_profile(self):
        profile = Profile.objects.create(user=self.user, theme=self.theme)
        layout = resolve_section_layout(profile, 'video_editor')
        self.assertFalse(layout['custom'])
        self.assertEqual(layout['order_keys'], self.CREATIVE_ORDER)
        self.assertEqual(layout['default_order'], self.CREATIVE_ORDER)

    def test_builder_panel_enabled_and_hides_links_row(self):
        self._login_with_theme()
        response = self.client.get(reverse('builder'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['section_layout_enabled'])
        row_keys = [row['key'] for row in response.context['section_rows']]
        self.assertEqual(row_keys, self.CREATIVE_ORDER)

    def test_ajax_save_rejects_unsupported_links_key(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(['projects', 'links']),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid_keys', response.json())
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])

    def test_ajax_save_theme_default_stores_nothing(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(self.CREATIVE_ORDER),
            'section_visibility': json.dumps({key: True for key in self.CREATIVE_ORDER}),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])
        self.assertEqual(profile.section_visibility, {})
        self.assertFalse(resolve_section_layout(profile, 'video_editor')['custom'])

    def test_preview_custom_order_emits_theme_selectors(self):
        profile = self._login_with_theme(is_public=True)
        profile.section_order = ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact']
        profile.save()

        response = self.client.get(reverse('preview', kwargs={'username': self.user.username}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # creators moved ahead of the work grid (#projects)
        self.assertLess(content.index('#creators { order: 1;'), content.index('#projects { order: 2;'))
        # no links rules — the theme has no #connect section
        self.assertNotIn('#connect', content)


class AnimatedDarkThemeLayoutTests(TestCase):
    """The animated_dark theme opens with its creators marquee right after
    the hero and renders social links inside its contact section, so its
    default order starts with creators and has no links key.
    """

    ANIMATED_DARK_ORDER = ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact']

    def setUp(self):
        self.user = User.objects.create_user(username='darkuser', email='dark@example.com', password='x')
        category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Animated Dark', category=category)

    def _login_with_theme(self, **profile_kwargs):
        profile = Profile.objects.create(user=self.user, theme=self.theme, **profile_kwargs)
        self.client.login(username='darkuser', password='x')
        return profile

    def test_supported_keys_match_theme_dom_order(self):
        self.assertEqual(supported_keys('video_editor', 'animated_dark'), self.ANIMATED_DARK_ORDER)

    def test_resolve_uses_theme_default_from_profile(self):
        profile = Profile.objects.create(user=self.user, theme=self.theme)
        layout = resolve_section_layout(profile, 'video_editor')
        self.assertFalse(layout['custom'])
        self.assertEqual(layout['order_keys'], self.ANIMATED_DARK_ORDER)
        self.assertEqual(layout['default_order'], self.ANIMATED_DARK_ORDER)

    def test_builder_panel_enabled_and_hides_links_row(self):
        self._login_with_theme()
        response = self.client.get(reverse('builder'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['section_layout_enabled'])
        row_keys = [row['key'] for row in response.context['section_rows']]
        self.assertEqual(row_keys, self.ANIMATED_DARK_ORDER)

    def test_ajax_save_rejects_unsupported_links_key(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(['projects', 'links']),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid_keys', response.json())
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])

    def test_ajax_save_theme_default_stores_nothing(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(self.ANIMATED_DARK_ORDER),
            'section_visibility': json.dumps({key: True for key in self.ANIMATED_DARK_ORDER}),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])
        self.assertEqual(profile.section_visibility, {})
        self.assertFalse(resolve_section_layout(profile, 'video_editor')['custom'])

    def test_preview_custom_order_emits_theme_selectors(self):
        profile = self._login_with_theme(is_public=True)
        profile.section_order = ['projects', 'creators', 'skills', 'experience', 'education', 'reviews', 'contact']
        profile.save()

        response = self.client.get(reverse('preview', kwargs={'username': self.user.username}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # projects promoted ahead of the creators marquee
        self.assertLess(content.index('#projects { order: 1;'), content.index('#creators { order: 2;'))
        # both the creators heading section and its marquee move together
        self.assertIn('.creators-marquee-container { order: 2; }', content)
        # no links rules — the theme has no #connect section
        self.assertNotIn('#connect', content)


class MonochromeThemeLayoutTests(TestCase):
    """The monochrome theme opens with a creators trust grid right after the
    hero and renders social links inside its contact section, so its default
    order starts with creators and has no links key.
    """

    MONOCHROME_ORDER = ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact']

    def setUp(self):
        self.user = User.objects.create_user(username='monouser', email='mono@example.com', password='x')
        category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Monochrome', category=category)

    def _login_with_theme(self, **profile_kwargs):
        profile = Profile.objects.create(user=self.user, theme=self.theme, **profile_kwargs)
        self.client.login(username='monouser', password='x')
        return profile

    def test_supported_keys_match_theme_dom_order(self):
        self.assertEqual(supported_keys('video_editor', 'monochrome'), self.MONOCHROME_ORDER)

    def test_resolve_uses_theme_default_from_profile(self):
        profile = Profile.objects.create(user=self.user, theme=self.theme)
        layout = resolve_section_layout(profile, 'video_editor')
        self.assertFalse(layout['custom'])
        self.assertEqual(layout['order_keys'], self.MONOCHROME_ORDER)
        self.assertEqual(layout['default_order'], self.MONOCHROME_ORDER)

    def test_builder_panel_enabled_and_hides_links_row(self):
        self._login_with_theme()
        response = self.client.get(reverse('builder'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['section_layout_enabled'])
        row_keys = [row['key'] for row in response.context['section_rows']]
        self.assertEqual(row_keys, self.MONOCHROME_ORDER)

    def test_ajax_save_rejects_unsupported_links_key(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(['projects', 'links']),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid_keys', response.json())
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])

    def test_ajax_save_theme_default_stores_nothing(self):
        profile = self._login_with_theme()
        response = self.client.post(reverse('ajax_save_section_layout'), {
            'section_order': json.dumps(self.MONOCHROME_ORDER),
            'section_visibility': json.dumps({key: True for key in self.MONOCHROME_ORDER}),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])
        self.assertEqual(profile.section_visibility, {})
        self.assertFalse(resolve_section_layout(profile, 'video_editor')['custom'])

    def test_preview_hiding_education_emits_rules(self):
        profile = self._login_with_theme(is_public=True)
        profile.section_visibility = {'education': False}
        profile.save()

        response = self.client.get(reverse('preview', kwargs={'username': self.user.username}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('#education { display: none !important; }', content)
        # dead-anchor cleanup hides the navbar link too
        self.assertIn('a[href="#education"] { display: none !important; }', content)
        # the resolved order still starts at the theme's DOM head
        self.assertIn('#creators { order: 1; }', content)
        # no links rules — the theme has no #connect section
        self.assertNotIn('#connect', content)


class RemainingVideoEditorThemeLayoutTests(TestCase):
    """Data-driven coverage for the remaining video_editor themes wired for
    section ordering: animated, cinematic, pro, yellow, cyan, editorial_studio.

    Each theme's expected order mirrors its hard-coded DOM. Narrower themes
    simply ship a shorter panel — cinematic has no reviews section, pro is a
    creators/reviews/contact landing page, and editorial_studio has no skills
    section. None of them renders a dedicated links section.
    """

    THEME_ORDERS = {
        'animated': ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact'],
        'cinematic': ['projects', 'skills', 'experience', 'education', 'creators', 'contact'],
        'pro': ['creators', 'reviews', 'contact'],
        'yellow': ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact'],
        'cyan': ['creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact'],
        'editorial_studio': ['projects', 'experience', 'education', 'creators', 'reviews', 'contact'],
    }

    # (promoted key, its selector, demoted key, its selector) for the preview
    # reorder assertion — the second DOM section is promoted to the top.
    PREVIEW_SWAPS = {
        'animated': ('projects', '#projects', 'creators', '#creators'),
        'cinematic': ('skills', '#skills', 'projects', '#work'),
        'pro': ('reviews', '#reviews', 'creators', '#creators'),
        'yellow': ('projects', '#projects', 'creators', '#creators'),
        'cyan': ('projects', '#projects', 'creators', '#creators'),
        'editorial_studio': ('experience', '#experience', 'projects', '#projects'),
    }

    def setUp(self):
        self.category = Category.objects.create(name='Video Editor')

    def _user_and_profile(self, theme_name, **profile_kwargs):
        """A fresh user per theme — Profile is one-to-one with User."""
        slug = theme_name.replace('_', '')
        user = User.objects.create_user(
            username=f'batch_{slug}', email=f'batch_{slug}@example.com', password='x')
        theme = Theme.objects.create(
            name=theme_name.replace('_', ' ').title(), category=self.category)
        profile = Profile.objects.create(user=user, theme=theme, **profile_kwargs)
        self.client.login(username=f'batch_{slug}', password='x')
        return profile

    def test_supported_keys_match_theme_dom_order(self):
        for theme, order in self.THEME_ORDERS.items():
            with self.subTest(theme=theme):
                self.assertEqual(supported_keys('video_editor', theme), order)

    def test_resolve_uses_theme_default_from_profile(self):
        for theme_name, order in self.THEME_ORDERS.items():
            with self.subTest(theme=theme_name):
                profile = self._user_and_profile(theme_name)
                layout = resolve_section_layout(profile, 'video_editor')
                self.assertFalse(layout['custom'])
                self.assertEqual(layout['order_keys'], order)
                self.assertEqual(layout['default_order'], order)

    def test_builder_panel_rows_match_theme_dom_order(self):
        for theme_name, order in self.THEME_ORDERS.items():
            with self.subTest(theme=theme_name):
                self._user_and_profile(theme_name)
                response = self.client.get(reverse('builder'))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['section_layout_enabled'])
                self.assertEqual(
                    [row['key'] for row in response.context['section_rows']], order)

    def test_ajax_save_rejects_unsupported_links_key(self):
        for theme_name, order in self.THEME_ORDERS.items():
            with self.subTest(theme=theme_name):
                profile = self._user_and_profile(theme_name)
                response = self.client.post(reverse('ajax_save_section_layout'), {
                    'section_order': json.dumps([order[0], 'links']),
                })
                self.assertEqual(response.status_code, 400)
                self.assertIn('links', response.json()['invalid_keys'])
                profile.refresh_from_db()
                self.assertEqual(profile.section_order, [])

    def test_ajax_save_theme_default_stores_nothing(self):
        for theme_name, order in self.THEME_ORDERS.items():
            with self.subTest(theme=theme_name):
                profile = self._user_and_profile(theme_name)
                response = self.client.post(reverse('ajax_save_section_layout'), {
                    'section_order': json.dumps(order),
                    'section_visibility': json.dumps({key: True for key in order}),
                })
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['success'])
                profile.refresh_from_db()
                self.assertEqual(profile.section_order, [])
                self.assertEqual(profile.section_visibility, {})
                self.assertFalse(resolve_section_layout(profile, 'video_editor')['custom'])

    def test_preview_custom_order_emits_theme_selectors(self):
        for theme_name, order in self.THEME_ORDERS.items():
            with self.subTest(theme=theme_name):
                promoted, promoted_sel, demoted, demoted_sel = self.PREVIEW_SWAPS[theme_name]
                profile = self._user_and_profile(theme_name, is_public=True)
                profile.section_order = [promoted] + [k for k in order if k != promoted]
                profile.save()

                response = self.client.get(
                    reverse('preview', kwargs={'username': profile.user.username}))
                self.assertEqual(response.status_code, 200)
                content = response.content.decode()
                self.assertLess(
                    content.index(f'{promoted_sel} {{ order: 1;'),
                    content.index(f'{demoted_sel} {{ order: 2;'))
                # none of these themes renders a dedicated links section
                self.assertNotIn('#connect', content)
