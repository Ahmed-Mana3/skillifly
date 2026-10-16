"""PR-3: video link lookup service. All network access is mocked."""
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase

from core import oembed
from core.testing_helpers import FakeResp, clear_cache, png_bytes

YT_ID = 'dQw4w9WgXcQ'
YT_OEMBED = {
    'title': 'Never Gonna Edit You Up',
    'thumbnail_url': f'https://i.ytimg.com/vi/{YT_ID}/hqdefault.jpg',
    'width': 200, 'height': 113,
}


class NormalizeUrlTests(SimpleTestCase):
    def test_adds_scheme_and_keeps_valid_links(self):
        self.assertEqual(oembed.normalize_url('youtube.com/watch?v=abc'), 'https://youtube.com/watch?v=abc')
        self.assertEqual(oembed.normalize_url('  http://vimeo.com/1  '), 'http://vimeo.com/1')

    def test_rejects_dangerous_or_unusable_input(self):
        for bad in (
            None, '', '   ', 'javascript:alert(1)', 'data:text/html,<b>x</b>',
            'ftp://example.com/video', 'two words.com', 'localhost', 'https://nodot',
            'x' * 501, 123, ['https://a.com'],
        ):
            self.assertIsNone(oembed.normalize_url(bad), bad)

    def test_provider_detection_by_hostname_not_substring(self):
        d = oembed.detect_provider
        self.assertEqual(d('https://www.youtube.com/watch?v=x'), 'youtube')
        self.assertEqual(d('https://youtu.be/x'), 'youtube')
        self.assertEqual(d('https://m.youtube.com/watch?v=x'), 'youtube')
        self.assertEqual(d('https://player.vimeo.com/video/1'), 'vimeo')
        self.assertEqual(d('https://www.tiktok.com/@a/video/1'), 'tiktok')
        self.assertEqual(d('https://www.instagram.com/reel/abc/'), 'instagram')
        self.assertEqual(d('https://drive.google.com/file/d/abc/view'), 'drive')
        self.assertEqual(d('https://fb.watch/abc'), 'facebook')
        # A hostile host that merely contains a provider name is not that provider.
        self.assertEqual(d('https://youtube.com.evil.io/watch?v=x'), 'other')
        self.assertEqual(d('https://notyoutube.com/watch?v=x'), 'other')


class FetchTests(TestCase):
    def setUp(self):
        clear_cache()

    def _get(self, payload=None, status=200):
        return patch('core.oembed.requests.get', return_value=FakeResp(status, payload))

    def test_youtube_link_variants(self):
        for link, reel in (
            (f'https://www.youtube.com/watch?v={YT_ID}', False),
            (f'https://youtu.be/{YT_ID}', False),
            (f'https://m.youtube.com/watch?v={YT_ID}&t=42s&list=PL123', False),
            (f'https://www.youtube.com/shorts/{YT_ID}', True),
        ):
            clear_cache()
            with self._get(YT_OEMBED) as get:
                meta = oembed.fetch(link)
            self.assertTrue(meta.ok, link)
            self.assertEqual(meta.provider, 'youtube')
            self.assertEqual(meta.title, 'Never Gonna Edit You Up')
            self.assertEqual(meta.video_type, 'reel' if reel else 'long', link)
            self.assertEqual(meta.thumbnail_url, f'https://i.ytimg.com/vi/{YT_ID}/hqdefault.jpg')
            self.assertEqual(
                meta.thumbnail_candidates[0], f'https://i.ytimg.com/vi/{YT_ID}/maxresdefault.jpg',
            )
            # The lookup always goes through the plain watch form.
            self.assertEqual(get.call_args.kwargs['params']['url'], f'https://www.youtube.com/watch?v={YT_ID}')
            self.assertEqual(meta.url, link)

    def test_vimeo(self):
        data = {'title': 'Cut', 'thumbnail_url': 'https://i.vimeocdn.com/video/1_1280.jpg', 'width': 1920, 'height': 1080}
        with self._get(data) as get:
            meta = oembed.fetch('https://vimeo.com/123456')
        self.assertTrue(meta.ok)
        self.assertEqual((meta.provider, meta.title, meta.video_type), ('vimeo', 'Cut', 'long'))
        self.assertEqual(meta.thumbnail_url, 'https://i.vimeocdn.com/video/1_1280.jpg')
        self.assertEqual(get.call_args.kwargs['params']['width'], 1280)

    def test_vertical_oembed_dimensions_mean_reel(self):
        data = {'title': 'V', 'thumbnail_url': 'https://i.vimeocdn.com/x.jpg', 'width': 720, 'height': 1280}
        with self._get(data):
            self.assertEqual(oembed.fetch('https://vimeo.com/9').video_type, 'reel')

    def test_tiktok_is_a_reel(self):
        data = {'title': 'Dance', 'thumbnail_url': 'https://p16.tiktokcdn.com/a.jpg'}
        with self._get(data):
            meta = oembed.fetch('https://www.tiktok.com/@user/video/123')
        self.assertEqual((meta.provider, meta.video_type, meta.title), ('tiktok', 'reel', 'Dance'))

    def test_tiktok_short_link_resolves_within_tiktok(self):
        head = FakeResp(302, headers={'Location': 'https://www.tiktok.com/@user/video/123'})
        with patch('core.oembed.requests.head', return_value=head), self._get({'title': 'T'}) as get:
            meta = oembed.fetch('https://vm.tiktok.com/ZMabc/')
        self.assertTrue(meta.ok)
        self.assertEqual(meta.url, 'https://www.tiktok.com/@user/video/123')
        self.assertEqual(get.call_args.kwargs['params']['url'], 'https://www.tiktok.com/@user/video/123')

    def test_tiktok_short_link_redirecting_off_tiktok_is_not_trusted(self):
        head = FakeResp(302, headers={'Location': 'https://evil.example.com/steal'})
        with patch('core.oembed.requests.head', return_value=head), self._get({'title': 'T'}) as get:
            meta = oembed.fetch('https://vm.tiktok.com/ZMabc/')
        self.assertEqual(meta.url, 'https://vm.tiktok.com/ZMabc/')
        self.assertNotIn('evil', str(get.call_args))

    def test_instagram_reel_needs_no_network(self):
        with patch('core.oembed.requests.get') as get, patch('core.oembed.requests.head') as head:
            meta = oembed.fetch('https://www.instagram.com/reel/Cabc123/')
        get.assert_not_called()
        head.assert_not_called()
        self.assertEqual((meta.ok, meta.provider, meta.video_type, meta.title, meta.thumbnail_url),
                         (True, 'instagram', 'reel', '', ''))

    def test_drive_needs_no_network(self):
        with patch('core.oembed.requests.get') as get:
            meta = oembed.fetch('https://drive.google.com/file/d/abc123/view')
        get.assert_not_called()
        self.assertEqual((meta.ok, meta.provider, meta.video_type), (True, 'drive', 'long'))

    def test_unknown_site_is_ok_but_bare(self):
        with patch('core.oembed.requests.get') as get:
            meta = oembed.fetch('https://behance.net/gallery/1/x')
        get.assert_not_called()
        self.assertEqual((meta.ok, meta.provider, meta.title), (True, 'other', ''))

    def test_error_mapping(self):
        link = f'https://www.youtube.com/watch?v={YT_ID}'
        # 400 is what YouTube really returns for a nonexistent/malformed video id (checked live).
        for status, expected in (
            (400, 'not_found'), (401, 'private'), (403, 'private'), (404, 'not_found'), (500, 'provider_error'),
        ):
            clear_cache()
            with self._get(None, status):
                meta = oembed.fetch(link)
            self.assertFalse(meta.ok)
            self.assertEqual(meta.error, expected, status)

    def test_hard_failures_are_only_the_reliable_ones(self):
        mk = lambda provider, error: oembed.VideoMeta(url='https://x.com', provider=provider, ok=False, error=error)
        self.assertTrue(oembed.is_hard_failure(mk('youtube', 'private')))
        self.assertTrue(oembed.is_hard_failure(mk('tiktok', 'private')))
        self.assertTrue(oembed.is_hard_failure(mk('youtube', 'not_found')))
        self.assertTrue(oembed.is_hard_failure(mk('vimeo', 'not_found')))
        # A TikTok 400 can mean "valid link oEmbed doesn't cover": warn, don't block.
        self.assertFalse(oembed.is_hard_failure(mk('tiktok', 'not_found')))
        for soft in ('timeout', 'network', 'provider_error', ''):
            self.assertFalse(oembed.is_hard_failure(mk('youtube', soft)), soft)

    def test_timeout_network_and_bad_json(self):
        link = f'https://www.youtube.com/watch?v={YT_ID}'
        with patch('core.oembed.requests.get', side_effect=requests.Timeout()):
            self.assertEqual(oembed.fetch(link).error, 'timeout')
        with patch('core.oembed.requests.get', side_effect=requests.ConnectionError()):
            self.assertEqual(oembed.fetch(link).error, 'network')
        with self._get(None, 200):  # 200 but no JSON body
            self.assertEqual(oembed.fetch(link).error, 'provider_error')

    def test_unexpected_exception_never_escapes(self):
        with patch('core.oembed.requests.get', side_effect=RuntimeError('boom')):
            meta = oembed.fetch(f'https://www.youtube.com/watch?v={YT_ID}')
        self.assertFalse(meta.ok)
        self.assertEqual(meta.error, 'provider_error')

    def test_invalid_input(self):
        for bad in ('', 'javascript:alert(1)', 'two words', None):
            meta = oembed.fetch(bad)
            self.assertFalse(meta.ok)
            self.assertEqual(meta.error, 'invalid')

    def test_success_is_cached_but_errors_are_not(self):
        link = f'https://www.youtube.com/watch?v={YT_ID}'
        with self._get(YT_OEMBED) as get:
            oembed.fetch(link)
            oembed.fetch(link)
        self.assertEqual(get.call_count, 1)

        clear_cache()
        with self._get(None, 401) as get:
            oembed.fetch(link)
            oembed.fetch(link)  # user fixed the privacy setting and pasted again
        self.assertEqual(get.call_count, 2)


class DownloadThumbnailTests(TestCase):
    JPG_URL = f'https://i.ytimg.com/vi/{YT_ID}/hqdefault.jpg'

    def _meta(self, *candidates):
        return oembed.VideoMeta(url='https://x.com', thumbnail_candidates=list(candidates))

    def _image_resp(self, **kw):
        return FakeResp(200, headers={'Content-Type': 'image/jpeg'}, content=png_bytes(fmt='JPEG'), **kw)

    def test_downloads_from_allowed_host(self):
        with patch('core.oembed.requests.get', return_value=self._image_resp()) as get:
            thumb = oembed.download_thumbnail(self._meta(self.JPG_URL))
        self.assertIsNotNone(thumb)
        self.assertTrue(thumb.name.startswith('oembed_') and thumb.name.endswith('.jpg'))
        self.assertGreater(thumb.size, 100)
        self.assertFalse(get.call_args.kwargs['allow_redirects'])  # never follow redirects

    def test_disallowed_hosts_are_never_requested(self):
        for url in (
            'https://evil.example.com/a.jpg',
            'http://i.ytimg.com/a.jpg',                   # not https
            'https://i.ytimg.com.evil.example.com/a.jpg',  # suffix trick
            'https://169.254.169.254/latest/meta-data',
            'https://localhost/a.jpg',
        ):
            with patch('core.oembed.requests.get') as get:
                self.assertIsNone(oembed.download_thumbnail(self._meta(url)), url)
            get.assert_not_called()

    def test_redirects_oversize_and_non_images_are_rejected(self):
        cases = {
            'redirect': FakeResp(302, headers={'Location': 'http://127.0.0.1/'}),
            'not found': FakeResp(404),
            'wrong content type': FakeResp(200, headers={'Content-Type': 'text/html'}, content=b'<html>'),
            'garbage bytes': FakeResp(200, headers={'Content-Type': 'image/jpeg'}, content=b'not an image' * 50),
            'too big': FakeResp(200, headers={'Content-Type': 'image/jpeg'},
                                content=b'\xff\xd8' + b'0' * (oembed.THUMB_MAX_BYTES + 10)),
            'too small': FakeResp(200, headers={'Content-Type': 'image/png'}, content=png_bytes(40, 40)),
        }
        for label, resp in cases.items():
            with patch('core.oembed.requests.get', return_value=resp):
                self.assertIsNone(oembed.download_thumbnail(self._meta(self.JPG_URL)), label)

    def test_falls_back_to_next_candidate_when_maxres_is_missing(self):
        maxres = f'https://i.ytimg.com/vi/{YT_ID}/maxresdefault.jpg'

        def fake_get(url, **kw):
            return FakeResp(404) if 'maxres' in url else self._image_resp()

        with patch('core.oembed.requests.get', side_effect=fake_get) as get:
            thumb = oembed.download_thumbnail(self._meta(maxres, self.JPG_URL))
        self.assertIsNotNone(thumb)
        self.assertEqual(get.call_count, 2)

    def test_network_errors_return_none(self):
        with patch('core.oembed.requests.get', side_effect=requests.Timeout()):
            self.assertIsNone(oembed.download_thumbnail(self._meta(self.JPG_URL)))
