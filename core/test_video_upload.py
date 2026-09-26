"""Tests for direct-to-Cloudflare video uploads (tus + webhook).

Covers the security-critical guarantees: the quota check runs before
Cloudflare is contacted, every read is scoped to the owning user, the webhook
rejects unsigned requests, and no video bytes or API token ever reach the
browser.
"""
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core import cloudflare_stream
from core.models import Profile, Project, Video

User = get_user_model()

GB = 1024 * 1024 * 1024
MB = 1024 * 1024


def make_ready_payload(uid, duration=12.5):
    """A Cloudflare webhook body for a successfully processed video.

    Mirrors a real ``ready`` callback, which carries both ``status.state`` and
    ``readyToStream``.
    """
    return {
        'uid': uid,
        'duration': duration,
        'readyToStream': True,
        'thumbnail': 'thumbnails/thumbnail.jpg',
        'playback': {
            'hls': f'https://customer-77q2hblzjugdia3y.cloudflarestream.com/{uid}/manifest/video.m3u8',
            'dash': f'https://customer-77q2hblzjugdia3y.cloudflarestream.com/{uid}/manifest/video.mpd',
        },
        'status': {'state': 'ready', 'pctComplete': '100'},
    }


def sign(body, secret, timestamp=None):
    """Build a valid Cloudflare ``Webhook-Signature`` header value.

    Cloudflare Stream uses ``time=<unix>,sig1=<hex-hmac>`` (not the ``t``/``v1``
    spelling used by some other providers).
    """
    ts = str(int(timestamp if timestamp is not None else time.time()))
    source = f'{ts}.'.encode() + body
    digest = hmac.new(secret.encode(), source, hashlib.sha256).hexdigest()
    return f'time={ts},sig1={digest}'


class VideoQuotaTests(TestCase):
    """Storage allowance = plan tier + purchased add-on; usage comes from rows."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='quota_editor', email='quota@example.com', password='pw12345!'
        )
        Profile.objects.get_or_create(user=self.user)

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB, VIDEO_STORAGE_PRO_BYTES=200 * MB)
    def test_free_tier_allowance(self):
        self.assertEqual(self.user.storage_quota_bytes, 100 * MB)

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB, VIDEO_STORAGE_PRO_BYTES=200 * MB)
    def test_storage_addon_adds_to_allowance(self):
        profile = self.user.profile
        profile.storage_addon_bytes = 50 * MB
        profile.save()
        self.assertEqual(self.user.storage_quota_bytes, 150 * MB)
        # A file that only fits once the add-on is purchased is now allowed.
        self.assertTrue(self.user.has_storage_room_for(120 * MB))

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB, VIDEO_STORAGE_PRO_BYTES=200 * MB)
    def test_used_bytes_reflects_live_uploads_only(self):
        Video.objects.create(user=self.user, cloudflare_uid='a', status='ready', size_bytes=30 * MB)
        Video.objects.create(user=self.user, cloudflare_uid='b', status='processing', size_bytes=20 * MB)
        Video.objects.create(user=self.user, cloudflare_uid='c', status='error', size_bytes=90 * MB)
        # The failed upload must not keep consuming space.
        self.assertEqual(self.user.storage_used_bytes, 50 * MB)
        self.assertEqual(self.user.storage_free_bytes, 50 * MB)

    def test_has_storage_room_for_rejects_bad_sizes(self):
        self.assertFalse(self.user.has_storage_room_for(0))
        self.assertFalse(self.user.has_storage_room_for(-1))
        self.assertFalse(self.user.has_storage_room_for(None))
        self.assertFalse(self.user.has_storage_room_for('not-a-number'))

    def test_free_bytes_never_goes_negative(self):
        Video.objects.create(user=self.user, cloudflare_uid='big', status='ready', size_bytes=999 * GB)
        self.assertEqual(self.user.storage_free_bytes, 0)
        self.assertFalse(self.user.has_storage_room_for(1))


@override_settings(
    CLOUDFLARE_ACCOUNT_ID='acct123',
    CLOUDFLARE_STREAM_API_TOKEN='server-side-token',
    CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN='customer-test.cloudflarestream.com',
)
class CreateVideoUploadTests(TestCase):
    """The create-upload endpoint: quota first, then Cloudflare, then a row."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='uploader', email='uploader@example.com', password='pw12345!'
        )
        Profile.objects.get_or_create(user=self.user)
        self.post_url = reverse('create_video_upload')

    def _post(self, body, **extra):
        return self.client.post(
            self.post_url, data=json.dumps(body), content_type='application/json', **extra
        )

    def test_requires_login(self):
        response = self._post({'filename': 'a.mp4', 'filesize': 10 * MB})
        self.assertEqual(response.status_code, 302)

    def _mock_cloudflare(self):
        return patch(
            'core.cloudflare_stream.requests.post',
            return_value=type('R', (), {
                'status_code': 201,
                'headers': {
                    'Location': 'https://upload.videodelivery.net/tus/abc123',
                    'stream-media-id': 'uid-abc123',
                },
            })(),
        )

    @override_settings(VIDEO_STORAGE_FREE_BYTES=10 * MB, VIDEO_STORAGE_PRO_BYTES=10 * MB)
    def test_quota_is_checked_before_cloudflare_is_called(self):
        self.client.force_login(self.user)
        with self._mock_cloudflare() as mocked:
            response = self._post({'filename': 'huge.mp4', 'filesize': 50 * MB})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()['code'], 'quota_exceeded')
        # The critical assertion: Cloudflare was never contacted.
        mocked.assert_not_called()
        self.assertEqual(Video.objects.count(), 0)

    def test_rejects_invalid_size(self):
        self.client.force_login(self.user)
        for size in (0, -1, None, 'abc'):
            response = self._post({'filename': 'a.mp4', 'filesize': size})
            self.assertEqual(response.status_code, 400, f'size={size!r}')
        self.assertEqual(Video.objects.count(), 0)

    @override_settings(VIDEO_MAX_UPLOAD_BYTES=5 * MB)
    def test_rejects_oversized_file(self):
        self.client.force_login(self.user)
        with self._mock_cloudflare() as mocked:
            response = self._post({'filename': 'a.mp4', 'filesize': 50 * MB})
        self.assertEqual(response.status_code, 400)
        mocked.assert_not_called()

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB)
    @patch('core.cloudflare_stream.requests.post')
    def test_creates_pending_video_and_returns_one_time_url(self, mocked):
        mocked.return_value = type('R', (), {
            'status_code': 201,
            'headers': {
                'Location': 'https://upload.videodelivery.net/tus/xyz',
                'stream-media-id': 'uid-xyz',
            },
        })()
        self.client.force_login(self.user)
        response = self._post({'filename': 'reel.mp4', 'filesize': 10 * MB})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['uploadURL'], 'https://upload.videodelivery.net/tus/xyz')

        video = Video.objects.get(pk=body['videoId'])
        self.assertEqual(video.cloudflare_uid, 'uid-xyz')
        self.assertEqual(video.status, 'pending')
        self.assertEqual(video.title, 'reel.mp4')
        self.assertEqual(video.size_bytes, 10 * MB)
        self.assertEqual(video.user, self.user)

    @patch('core.cloudflare_stream.requests.post')
    def test_sends_tus_headers_and_never_leaks_the_token(self, mocked):
        mocked.return_value = type('R', (), {
            'status_code': 201,
            'headers': {'Location': 'https://u/1', 'stream-media-id': 'uid-1'},
        })()
        self.client.force_login(self.user)
        self._post({'filename': 'clip.mov', 'filesize': 10 * MB})

        sent_headers = mocked.call_args.kwargs['headers']
        self.assertEqual(sent_headers['Tus-Resumable'], '1.0.0')
        self.assertEqual(sent_headers['Upload-Length'], str(10 * MB))
        self.assertEqual(sent_headers['Upload-Creator'], str(self.user.id))
        self.assertIn('name ', sent_headers['Upload-Metadata'])
        # The token goes out in the Authorization header and nowhere else.
        self.assertIn('server-side-token', sent_headers['Authorization'])

    @patch('core.cloudflare_stream.requests.post')
    def test_token_never_appears_in_the_response(self, mocked):
        mocked.return_value = type('R', (), {
            'status_code': 201,
            'headers': {'Location': 'https://u/1', 'stream-media-id': 'uid-1'},
        })()
        self.client.force_login(self.user)
        response = self._post({'filename': 'a.mp4', 'filesize': 10 * MB})
        self.assertNotIn('server-side-token', response.content.decode())

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB)
    @patch('core.cloudflare_stream.requests.post')
    def test_cannot_attach_to_another_users_project(self, mocked):
        mocked.return_value = type('R', (), {
            'status_code': 201,
            'headers': {'Location': 'https://u/1', 'stream-media-id': 'uid-1'},
        })()
        other = User.objects.create_user(
            username='intruder', email='intruder@example.com', password='pw12345!'
        )
        victim_project = Project.objects.create(user=other, title='Not yours')

        self.client.force_login(self.user)
        response = self._post({
            'filename': 'a.mp4', 'filesize': 10 * MB, 'project_id': victim_project.id,
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Video.objects.filter(project=victim_project).exists())
        # Rejected before Cloudflare was asked to create anything.
        mocked.assert_not_called()

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB)
    @patch('core.cloudflare_stream.requests.post')
    def test_cloudflare_failure_returns_502_without_creating_a_row(self, mocked):
        mocked.return_value = type('R', (), {'status_code': 400, 'headers': {}, 'text': 'no'})()
        self.client.force_login(self.user)
        response = self._post({'filename': 'a.mp4', 'filesize': 10 * MB})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Video.objects.count(), 0)

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB)
    @patch('core.cloudflare_stream.requests.post')
    def test_missing_location_header_returns_502(self, mocked):
        mocked.return_value = type('R', (), {
            'status_code': 201, 'headers': {'stream-media-id': 'uid-1'}, 'text': 'ok',
        })()
        self.client.force_login(self.user)
        self.assertEqual(
            self._post({'filename': 'a.mp4', 'filesize': 10 * MB}).status_code, 502
        )

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB)
    @patch('core.cloudflare_stream.requests.post')
    def test_rejects_non_post(self, mocked):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.post_url).status_code, 405)


@override_settings(
    CLOUDFLARE_ACCOUNT_ID='acct123',
    CLOUDFLARE_STREAM_API_TOKEN='server-side-token',
    CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN='customer-test.cloudflarestream.com',
)
class VideoStatusEndpointTests(TestCase):
    """The polling fallback, and per-user isolation."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='owner', email='owner@example.com', password='pw12345!'
        )
        Profile.objects.get_or_create(user=self.user)
        self.other = User.objects.create_user(
            username='nosy', email='nosy@example.com', password='pw12345!'
        )
        self.video = Video.objects.create(
            user=self.user, cloudflare_uid='uid-1', status='pending', size_bytes=10 * MB
        )

    def test_requires_login(self):
        self.assertEqual(
            self.client.get(reverse('video_status', args=[self.video.id])).status_code, 302
        )

    def test_other_user_gets_404_not_200(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('video_status', args=[self.video.id]))
        self.assertEqual(response.status_code, 404)

    def test_owner_sees_their_own_status(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('video_status', args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'pending')

    @patch('core.cloudflare_stream.requests.get')
    def test_falls_back_to_cloudflare_and_marks_ready(self, mocked):
        mocked.return_value = type('R', (), {
            'status_code': 200,
            'json': lambda self: {
                'result': {
                    'readyToStream': True,
                    'duration': 31.2,
                    'thumbnail': 'thumbnails/t.jpg',
                    'playback': {'hls': 'https://cdn/manifest/video.m3u8', 'dash': 'https://cdn/v.mpd'},
                    'status': {'state': 'ready'},
                }
            },
        })()
        self.client.force_login(self.user)
        body = self.client.get(reverse('video_status', args=[self.video.id])).json()

        self.assertEqual(body['status'], 'ready')
        self.assertEqual(body['duration'], 31.2)
        self.assertEqual(body['hls'], 'https://cdn/manifest/video.m3u8')
        # Thumbnail is expanded to an absolute URL so the browser can load it.
        self.assertTrue(body['thumbnail'].startswith('https://'))
        # The player URL is built server-side.
        self.assertIn('uid-1/iframe', body['embed'])

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, 'ready')
        self.assertEqual(self.video.playback_hls_url, 'https://cdn/manifest/video.m3u8')

    @patch('core.cloudflare_stream.requests.get')
    def test_cloudflare_outage_does_not_break_status(self, mocked):
        # A provider outage must degrade to "still processing", never a 500.
        mocked.side_effect = requests.ConnectionError('network down')
        self.client.force_login(self.user)
        response = self.client.get(reverse('video_status', args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'pending')

    @override_settings(CLOUDFLARE_STREAM_API_TOKEN='')
    def test_status_survives_a_missing_server_token(self):
        # If the token is revoked while a page is open, polling must not 500.
        self.client.force_login(self.user)
        response = self.client.get(reverse('video_status', args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'pending')

    @patch('core.cloudflare_stream.requests.get')
    def test_ready_videos_do_not_hit_cloudflare(self, mocked):
        self.video.status = 'ready'
        self.video.save()
        self.client.force_login(self.user)
        self.client.get(reverse('video_status', args=[self.video.id]))
        mocked.assert_not_called()


@override_settings(
    CLOUDFLARE_ACCOUNT_ID='acct123',
    CLOUDFLARE_STREAM_API_TOKEN='server-side-token',
    CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN='customer-test.cloudflarestream.com',
    CLOUDFLARE_STREAM_WEBHOOK_SECRET='topsecret',
)
class CloudflareWebhookTests(TestCase):
    """Signature verification is mandatory and fails closed."""

    def setUp(self):
        self.url = reverse('cloudflare_stream_webhook')
        self.user = User.objects.create_user(
            username='hookuser', email='hook@example.com', password='pw12345!'
        )
        self.video = Video.objects.create(
            user=self.user, cloudflare_uid='uid-hook', status='processing', size_bytes=10 * MB
        )

    def _post(self, payload, signature):
        return self.client.post(
            self.url, data=json.dumps(payload), content_type='application/json',
            HTTP_WEBHOOK_SIGNATURE=signature,
        )

    def test_rejects_missing_signature(self):
        response = self._post(make_ready_payload('uid-hook'), '')
        self.assertEqual(response.status_code, 403)

    def test_rejects_garbage_signature(self):
        self.assertEqual(
            self._post(make_ready_payload('uid-hook'), 'nonsense').status_code, 403
        )

    def test_rejects_forged_signature(self):
        self.assertEqual(
            self._post(make_ready_payload('uid-hook'), 'time=1,sig1=deadbeef').status_code, 403
        )

    def test_rejects_signature_made_with_the_wrong_secret(self):
        body = json.dumps(make_ready_payload('uid-hook')).encode()
        response = self._post(make_ready_payload('uid-hook'), sign(body, 'wrong-secret'))
        self.assertEqual(response.status_code, 403)

    def test_rejects_stale_timestamp(self):
        body = json.dumps(make_ready_payload('uid-hook')).encode()
        old = time.time() - 3600
        response = self._post(make_ready_payload('uid-hook'), sign(body, 'topsecret', timestamp=old))
        self.assertEqual(response.status_code, 403)

    def test_is_csrf_exempt(self):
        # No CSRF token is sent, yet a correctly signed request is accepted.
        body = json.dumps(make_ready_payload('uid-hook')).encode()
        response = self._post(make_ready_payload('uid-hook'), sign(body, 'topsecret'))
        self.assertEqual(response.status_code, 200)

    def test_ready_payload_updates_the_row(self):
        payload = make_ready_payload('uid-hook')
        body = json.dumps(payload).encode()
        self._post(payload, sign(body, 'topsecret'))

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, 'ready')
        self.assertEqual(self.video.duration_seconds, 12.5)
        self.assertIn('thumbnails/thumbnail.jpg', self.video.thumbnail_url)
        self.assertTrue(self.video.playback_hls_url.endswith('.m3u8'))
        self.assertTrue(self.video.playback_dash_url.endswith('.mpd'))

    def test_error_payload_records_the_reason(self):
        payload = {
            'uid': 'uid-hook',
            'status': {'state': 'error', 'errReasonText': 'Invalid video file'},
        }
        body = json.dumps(payload).encode()
        self._post(payload, sign(body, 'topsecret'))

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, 'error')
        self.assertEqual(self.video.error_message, 'Invalid video file')

    def test_unknown_uid_is_acknowledged_not_an_error(self):
        payload = make_ready_payload('uid-does-not-exist')
        body = json.dumps(payload).encode()
        response = self._post(payload, sign(body, 'topsecret'))
        # 200 stops Cloudflare retrying a video we will never claim.
        self.assertEqual(response.status_code, 200)

    def test_body_tampering_after_signing_is_rejected(self):
        body = json.dumps(make_ready_payload('uid-hook')).encode()
        signature = sign(body, 'topsecret')
        tampered = json.dumps(make_ready_payload('uid-other')).encode()
        response = self.client.post(
            self.url, data=tampered, content_type='application/json',
            HTTP_WEBHOOK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(CLOUDFLARE_STREAM_WEBHOOK_SECRET='')
    def test_fails_closed_when_no_secret_configured(self):
        body = json.dumps(make_ready_payload('uid-hook')).encode()
        # An attacker could forge this if an empty key were accepted.
        response = self._post(make_ready_payload('uid-hook'), sign(body, ''))
        self.assertEqual(response.status_code, 403)

    def test_rejects_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_ready_video_points_its_project_at_the_player(self):
        project = Project.objects.create(user=self.user, title='My reel')
        self.video.project = project
        self.video.save()
        payload = make_ready_payload('uid-hook')
        body = json.dumps(payload).encode()
        self._post(payload, sign(body, 'topsecret'))

        project.refresh_from_db()
        self.assertIn('cloudflarestream.com', project.url)
        self.assertTrue(project.embed_url)


class WebhookSignatureUnitTests(TestCase):
    def test_returns_false_for_empty_header(self):
        self.assertFalse(cloudflare_stream.verify_webhook_signature('', b'{}'))

    @override_settings(CLOUDFLARE_STREAM_WEBHOOK_SECRET='abc')
    def test_accepts_a_well_formed_signature(self):
        body = b'{"uid":"x"}'
        self.assertTrue(cloudflare_stream.verify_webhook_signature(sign(body, 'abc'), body))

    @override_settings(CLOUDFLARE_STREAM_WEBHOOK_SECRET='abc')
    def test_rejects_malformed_header_shapes(self):
        for header in ('garbage', 'time=abc,sig1=x', 'sig1=x', 'time=123', ''):
            self.assertFalse(
                cloudflare_stream.verify_webhook_signature(header, b'{}'), header
            )


class UploadMetadataUnitTests(TestCase):
    def test_encodes_each_pair_and_skips_none(self):
        value = cloudflare_stream.build_upload_metadata(
            name='my clip.mp4', maxdurationseconds=None, other='x'
        )
        self.assertEqual(value, 'name bXkgY2xpcC5tcDQ=,other eA==')

    def test_empty_when_nothing_given(self):
        self.assertEqual(cloudflare_stream.build_upload_metadata(), '')


class ApplyStreamResultTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='applier', email='applier@example.com', password='pw12345!'
        )
        self.video = Video.objects.create(
            user=self.user, cloudflare_uid='uid-apply', status='pending'
        )

    @override_settings(CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN='customer-test.cloudflarestream.com')
    def test_uploaded_state_becomes_processing(self):
        changed = cloudflare_stream.apply_stream_result(
            self.video, {'status': {'state': 'uploading'}}
        )
        self.assertTrue(changed)
        self.assertEqual(self.video.status, 'processing')

    def test_empty_result_changes_nothing(self):
        self.assertFalse(cloudflare_stream.apply_stream_result(self.video, {}))
        self.assertFalse(cloudflare_stream.apply_stream_result(self.video, None))
        self.assertEqual(self.video.status, 'pending')

    def test_ready_to_stream_required_before_marking_ready(self):
        # Cloudflare can report state=ready before playback exists.
        cloudflare_stream.apply_stream_result(
            self.video, {'status': {'state': 'ready'}, 'readyToStream': False}
        )
        self.assertEqual(self.video.status, 'pending')


@override_settings(
    CLOUDFLARE_ACCOUNT_ID='acct123',
    CLOUDFLARE_STREAM_API_TOKEN='server-side-token',
    CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN='customer-test.cloudflarestream.com',
)
class UploadPageTests(TestCase):
    """The page itself, and the bilingual route wiring."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='pager', email='pager@example.com', password='pw12345!'
        )
        Profile.objects.get_or_create(user=self.user)

    def test_requires_login(self):
        self.assertEqual(self.client.get(reverse('upload_video')).status_code, 302)

    def test_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('upload_video'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-vu')
        self.assertContains(response, 'tus-js-client')
        # The one-time upload URL is fetched from our endpoint, not handed to
        # the browser pre-signed, and the API token is never in the markup.
        self.assertContains(response, reverse('create_video_upload'))
        self.assertNotContains(response, 'server-side-token')

    @override_settings(CLOUDFLARE_STREAM_API_TOKEN='')
    def test_shows_a_graceful_notice_when_the_provider_is_unconfigured(self):
        # Better a clear message than a dropzone that cannot possibly work.
        self.client.force_login(self.user)
        response = self.client.get(reverse('upload_video'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'tus-js-client')
        self.assertContains(response, 'not available right now')

    def test_arabic_page_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('arabic_upload_video'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_arabic_page'])

    def test_client_account_is_sent_to_its_own_dashboard(self):
        from core.models import UserAccount
        client = User.objects.create_user(
            username='clienty', email='clienty@example.com', password='pw12345!'
        )
        UserAccount.objects.create(user=client, account_type='client')
        self.client.force_login(client)
        self.assertEqual(self.client.get(reverse('upload_video')).status_code, 302)

    def test_route_map_has_both_directions(self):
        from core.middleware import LanguagePreferenceMiddleware
        routes = LanguagePreferenceMiddleware.ROUTE_MAP
        self.assertEqual(
            routes['/dashboard/videos/upload/'], '/ar/dashboard/videos/upload/'
        )
        self.assertEqual(
            routes['/ar/dashboard/videos/upload/'], '/dashboard/videos/upload/'
        )

    def test_language_cookie_redirects_to_the_arabic_twin(self):
        self.client.force_login(self.user)
        self.client.cookies['skillifly_lang'] = 'ar'
        response = self.client.get(reverse('upload_video'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/ar/dashboard/videos/upload/')

    def test_dashboard_links_to_the_upload_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, reverse('upload_video'))

    def test_page_exposes_the_cancel_endpoint(self):
        # The client needs this to release its storage reservation.
        self.client.force_login(self.user)
        response = self.client.get(reverse('upload_video'))
        self.assertContains(response, reverse('cancel_video_upload', args=[0]))


@override_settings(
    CLOUDFLARE_ACCOUNT_ID='acct123',
    CLOUDFLARE_STREAM_API_TOKEN='server-side-token',
    CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN='customer-test.cloudflarestream.com',
)
class CancelVideoUploadTests(TestCase):
    """Cancelling must give the reserved storage back."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='canceller', email='cancel@example.com', password='pw12345!'
        )
        Profile.objects.get_or_create(user=self.user)
        self.video = Video.objects.create(
            user=self.user, cloudflare_uid='uid-cancel', status='pending', size_bytes=40 * MB
        )
        self.url = reverse('cancel_video_upload', args=[self.video.id])

    @override_settings(VIDEO_STORAGE_FREE_BYTES=100 * MB, VIDEO_STORAGE_PRO_BYTES=100 * MB)
    @patch('core.cloudflare_stream.requests.delete')
    def test_cancel_deletes_the_row_and_the_cloudflare_video(self, mocked):
        mocked.return_value = type('R', (), {'status_code': 200})()
        self.client.force_login(self.user)

        # The reservation is held before the cancel.
        self.assertEqual(self.user.storage_used_bytes, 40 * MB)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['cancelled'])
        self.assertFalse(Video.objects.filter(pk=self.video.pk).exists())
        # Space is released immediately.
        self.assertEqual(self.user.storage_used_bytes, 0)
        # And the bytes are not left sitting on Cloudflare.
        self.assertTrue(mocked.called)
        self.assertIn('uid-cancel', mocked.call_args[0][0])

    def test_requires_login(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)

    def test_other_users_video_is_404(self):
        intruder = User.objects.create_user(
            username='nosy2', email='nosy2@example.com', password='pw12345!'
        )
        self.client.force_login(intruder)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertTrue(Video.objects.filter(pk=self.video.pk).exists())

    def test_rejects_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    @patch('core.cloudflare_stream.requests.delete')
    def test_finished_videos_cannot_be_cancelled(self, mocked):
        # A published video is content, not a reservation — do not destroy it.
        self.video.status = 'ready'
        self.video.save()
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Video.objects.filter(pk=self.video.pk).exists())
        mocked.assert_not_called()

    @patch('core.cloudflare_stream.requests.delete')
    def test_row_is_released_even_if_cloudflare_delete_fails(self, mocked):
        mocked.side_effect = requests.ConnectionError('provider down')
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        # The local reservation is what blocks the user's next upload, so it goes
        # regardless of the provider call.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Video.objects.filter(pk=self.video.pk).exists())
        self.assertEqual(self.user.storage_used_bytes, 0)


@override_settings(
    CLOUDFLARE_ACCOUNT_ID='acct123',
    CLOUDFLARE_STREAM_API_TOKEN='server-side-token',
)
class ReapAbandonedUploadsTests(TestCase):
    """The reaper releases reservations whose browser went away."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='reaper', email='reaper@example.com', password='pw12345!'
        )
        Profile.objects.get_or_create(user=self.user)

    def _video(self, status, age_hours):
        from datetime import timedelta

        from django.utils import timezone

        video = Video.objects.create(
            user=self.user, cloudflare_uid=f'uid-{status}-{age_hours}',
            status=status, size_bytes=10 * MB,
        )
        # created_at is auto_now_add, so age it with an explicit UPDATE.
        if age_hours:
            Video.objects.filter(pk=video.pk).update(
                created_at=timezone.now() - timedelta(hours=age_hours)
            )
            video.refresh_from_db()
        return video

    def _reap(self, hours=1, **kw):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('reap_abandoned_uploads', f'--hours={hours}', stdout=out, **kw)
        return out.getvalue()

    def test_deletes_old_pending_uploads(self):
        old = self._video('pending', 5)
        self._reap()
        self.assertFalse(Video.objects.filter(pk=old.pk).exists())

    def test_leaves_recent_uploads_alone(self):
        # A user mid-upload must not have their reservation pulled out.
        fresh = self._video('pending', 0)
        self._reap(hours=1)
        self.assertTrue(Video.objects.filter(pk=fresh.pk).exists())

    def test_never_deletes_finished_videos(self):
        ready = self._video('ready', 48)
        errored = self._video('error', 48)
        self._reap()
        self.assertTrue(Video.objects.filter(pk=ready.pk).exists())
        self.assertTrue(Video.objects.filter(pk=errored.pk).exists())

    def test_dry_run_deletes_nothing(self):
        old = self._video('pending', 5)
        output = self._reap(dry_run=True)
        self.assertIn('Would delete', output)
        self.assertTrue(Video.objects.filter(pk=old.pk).exists())

    @patch('core.cloudflare_stream.requests.delete')
    def test_asks_cloudflare_to_drop_the_media(self, mocked):
        mocked.return_value = type('R', (), {'status_code': 200})()
        self._video('pending', 5)
        self._reap()
        self.assertTrue(mocked.called)

    def test_reports_cleanly_when_there_is_nothing_to_do(self):
        self.assertIn('No abandoned uploads', self._reap())
