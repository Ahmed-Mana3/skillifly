"""
Video link lookup for onboarding.

Turns a pasted video URL into a title, thumbnail and reel/long guess using the
providers' free, keyless oEmbed endpoints (YouTube, Vimeo, TikTok). Every
function is best-effort and never raises: a failed lookup degrades to "ask the
user to type a title", it never blocks onboarding.

Security: the only URLs this module fetches are (a) the fixed oEmbed endpoints,
(b) `vm.tiktok.com` / `vt.tiktok.com` short links, followed by hand and only
across tiktok.com hosts, and (c) thumbnail URLs on an allow-list of image CDN
hosts, fetched without following redirects.
"""
import hashlib
import io
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

import requests
from django.core.cache import cache
from django.core.files.base import ContentFile

logger = logging.getLogger('core')

USER_AGENT = 'SkilliflyBot/1.0 (+https://skillifly.cloud)'
LOOKUP_TIMEOUT = 3
THUMB_TIMEOUT = 4
THUMB_MAX_BYTES = 3 * 1024 * 1024
THUMB_MIN_WIDTH = 200
CACHE_SECONDS = 24 * 60 * 60
MAX_URL_LENGTH = 500  # Project.url max_length
MAX_REDIRECT_HOPS = 3

OEMBED_ENDPOINTS = {
    'youtube': 'https://www.youtube.com/oembed',
    'vimeo': 'https://vimeo.com/api/oembed.json',
    'tiktok': 'https://www.tiktok.com/oembed',
}

# Image CDNs we are willing to download a thumbnail from.
THUMB_HOST_SUFFIXES = (
    '.ytimg.com', '.vimeocdn.com', '.tiktokcdn.com',
    '.tiktokcdn-us.com', '.tiktokcdn-eu.com', '.ibyteimg.com',
)

_HOSTNAME_RE = re.compile(r'[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+', re.I)
_SCHEME_RE = re.compile(r'^([a-z][a-z0-9+.\-]*)://', re.I)
_YOUTUBE_ID_RE = re.compile(
    r'(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:shorts/|live/|(?:v|e(?:mbed)?)/|.*[?&]v=))([A-Za-z0-9_-]{11})'
)
_IMAGE_EXT = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}


@dataclass
class VideoMeta:
    url: str                      # normalized link that gets stored on Project.url
    provider: str = 'other'       # youtube | vimeo | tiktok | instagram | drive | facebook | other
    title: str = ''
    thumbnail_url: str = ''       # safe to show in the browser preview card
    thumbnail_candidates: list = field(default_factory=list)  # tried in order when downloading
    video_type: str = 'long'      # 'reel' | 'long'
    ok: bool = True
    error: str = ''               # '' | invalid | private | not_found | timeout | network | provider_error


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def normalize_url(raw):
    """Return a clean http(s) URL, or None when `raw` isn't a usable link."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > MAX_URL_LENGTH or re.search(r'\s', url):
        return None

    scheme = _SCHEME_RE.match(url)
    if scheme:
        if scheme.group(1).lower() not in ('http', 'https'):
            return None
    else:
        url = 'https://' + url

    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
    except ValueError:
        return None
    if not _HOSTNAME_RE.fullmatch(host):
        return None
    return url


def _host(url):
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def _host_is(host, domain):
    return host == domain or host.endswith('.' + domain)


def detect_provider(url):
    host = _host(url)
    if host == 'youtu.be' or _host_is(host, 'youtube.com') or _host_is(host, 'youtube-nocookie.com'):
        return 'youtube'
    if _host_is(host, 'vimeo.com'):
        return 'vimeo'
    if _host_is(host, 'tiktok.com'):
        return 'tiktok'
    if _host_is(host, 'instagram.com'):
        return 'instagram'
    if host == 'drive.google.com':
        return 'drive'
    if _host_is(host, 'facebook.com') or host == 'fb.watch':
        return 'facebook'
    return 'other'


def _youtube_id(url):
    m = _YOUTUBE_ID_RE.search(url)
    return m.group(1) if m else None


def _guess_video_type(provider, url, width=None, height=None):
    path = urlsplit(url).path.lower()
    if provider == 'tiktok':
        return 'reel'
    if provider == 'youtube' and '/shorts/' in path:
        return 'reel'
    if provider == 'instagram' and ('/reel/' in path or '/reels/' in path):
        return 'reel'
    try:
        if width and height and int(height) > int(width):
            return 'reel'
    except (TypeError, ValueError):
        pass
    return 'long'


def _resolve_tiktok_short(url):
    """Follow vm./vt.tiktok.com redirects by hand, staying on tiktok.com hosts."""
    host = _host(url)
    if host not in ('vm.tiktok.com', 'vt.tiktok.com'):
        return url
    current = url
    for _ in range(MAX_REDIRECT_HOPS):
        resp = requests.head(
            current, allow_redirects=False, timeout=LOOKUP_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
        )
        location = resp.headers.get('Location') if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308) else None
        if not location:
            return current
        nxt = normalize_url(location)
        if not nxt or not _host_is(_host(nxt), 'tiktok.com'):
            return url  # redirected off tiktok.com: don't trust it
        current = nxt
        if _host(current) not in ('vm.tiktok.com', 'vt.tiktok.com'):
            return current
    return current


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _cache_key(url):
    return 'oembed:' + hashlib.sha1(url.encode('utf-8')).hexdigest()


def _error_for_status(status):
    if status in (401, 403):
        return 'private'
    # YouTube answers 400 (not 404) for a nonexistent or malformed video id.
    if status in (400, 404):
        return 'not_found'
    return 'provider_error'


# Providers whose "not found" answer is reliable enough to refuse the link. For others
# (e.g. TikTok) a 400 can also mean "a valid link of a kind oEmbed doesn't cover", and
# blocking those would cost activations.
RELIABLE_NOT_FOUND = frozenset({'youtube', 'vimeo'})


def is_hard_failure(meta):
    """True when the link can't work for visitors and shouldn't be added."""
    return meta.error == 'private' or (meta.error == 'not_found' and meta.provider in RELIABLE_NOT_FOUND)


def _lookup(provider, url):
    """Query the provider's oEmbed endpoint. Returns a VideoMeta (ok or with error)."""
    params = {'url': url, 'format': 'json'}
    if provider == 'youtube':
        vid = _youtube_id(url)
        if vid:
            # Shorts/live links are looked up through the plain watch form.
            params['url'] = f'https://www.youtube.com/watch?v={vid}'
    if provider == 'vimeo':
        params['width'] = 1280  # asks Vimeo for a large thumbnail
    try:
        resp = requests.get(
            OEMBED_ENDPOINTS[provider], params=params, timeout=LOOKUP_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
        )
    except requests.Timeout:
        return VideoMeta(url=url, provider=provider, ok=False, error='timeout')
    except requests.RequestException:
        return VideoMeta(url=url, provider=provider, ok=False, error='network')

    if resp.status_code != 200:
        return VideoMeta(url=url, provider=provider, ok=False, error=_error_for_status(resp.status_code))
    try:
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError('not an object')
    except ValueError:
        return VideoMeta(url=url, provider=provider, ok=False, error='provider_error')

    title = str(data.get('title') or '').strip()[:500]
    thumb = str(data.get('thumbnail_url') or '').strip()
    candidates = []
    display_thumb = thumb
    if provider == 'youtube':
        vid = _youtube_id(url)
        if vid:
            candidates.append(f'https://i.ytimg.com/vi/{vid}/maxresdefault.jpg')
            display_thumb = f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'  # always exists
            candidates.append(display_thumb)
    if thumb and thumb not in candidates:
        candidates.append(thumb)
    return VideoMeta(
        url=url, provider=provider, title=title,
        thumbnail_url=display_thumb, thumbnail_candidates=candidates,
        video_type=_guess_video_type(provider, url, data.get('width'), data.get('height')),
    )


def fetch(url):
    """Look up a video link. Cached for 24 h (successes only). Never raises."""
    try:
        normalized = normalize_url(url)
        if not normalized:
            return VideoMeta(url=str(url or ''), ok=False, error='invalid')

        key = _cache_key(normalized)
        cached = cache.get(key)
        if cached:
            return VideoMeta(**cached)

        try:
            resolved = _resolve_tiktok_short(normalized)
        except requests.RequestException:
            resolved = normalized  # keep the short link; lookup below may still work

        provider = detect_provider(resolved)
        if provider in OEMBED_ENDPOINTS:
            meta = _lookup(provider, resolved)
        else:
            # Instagram, Drive, Facebook, anything else: no public lookup. The user
            # types a title; the link still embeds via Project.embed_url.
            meta = VideoMeta(
                url=resolved, provider=provider,
                video_type=_guess_video_type(provider, resolved),
            )
        if meta.ok:
            cache.set(key, asdict(meta), CACHE_SECONDS)
        return meta
    except Exception:
        logger.exception('oembed.fetch failed for %r', url)
        return VideoMeta(url=str(url or ''), ok=False, error='provider_error')


# ---------------------------------------------------------------------------
# Thumbnail download
# ---------------------------------------------------------------------------

def _host_allowed_for_thumbs(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != 'https':
        return False
    host = (parts.hostname or '').lower()
    return any(host.endswith(suffix) for suffix in THUMB_HOST_SUFFIXES)


def _download_image(url):
    """Download one thumbnail. Returns (bytes, ext) or None. Never raises."""
    if not _host_allowed_for_thumbs(url):
        return None
    try:
        with requests.get(
            url, stream=True, timeout=THUMB_TIMEOUT, allow_redirects=False,
            headers={'User-Agent': USER_AGENT},
        ) as resp:
            if resp.status_code != 200:
                return None
            if not (resp.headers.get('Content-Type') or '').lower().startswith('image/'):
                return None
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=16384):
                buf.extend(chunk)
                if len(buf) > THUMB_MAX_BYTES:
                    return None
        data = bytes(buf)
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            fmt, width = im.format, im.width
            im.verify()
        if fmt not in _IMAGE_EXT or width < THUMB_MIN_WIDTH:
            return None
        return data, _IMAGE_EXT[fmt]
    except Exception:
        logger.debug('Thumbnail download failed for %s', url, exc_info=True)
        return None


def download_thumbnail(meta):
    """Download the first usable thumbnail for `meta` as a ContentFile, or None."""
    try:
        candidates = list(meta.thumbnail_candidates or [])
        if not candidates and meta.thumbnail_url:
            candidates = [meta.thumbnail_url]
        for candidate in candidates[:4]:
            result = _download_image(candidate)
            if result:
                data, ext = result
                return ContentFile(data, name=f'oembed_{uuid.uuid4().hex[:12]}.{ext}')
    except Exception:
        logger.debug('download_thumbnail failed', exc_info=True)
    return None
