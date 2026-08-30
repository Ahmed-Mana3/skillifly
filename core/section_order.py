"""Shared section-layout configuration.

Single source of truth for the orderable portfolio sections: canonical keys,
per-theme-family support, defaults, display metadata, CSS selector candidates,
presets, and POST sanitization. Used by the builder views (save + context +
AJAX autosave endpoint) and the portfolios preview_view (render context).

Design notes
------------
- Canonical keys are stable IDs (``projects``, ``skills``, ...) that never
  change even though DOM ids differ per theme (``#portfolio`` vs ``#work``).
  ``SECTION_META[key]['selectors']`` lists every known candidate; rules that
  match nothing are harmless.
- Visibility is stored separately on ``Profile.section_visibility`` as a
  partial map ``{key: bool}``; a missing key means "visible".
- Users who never saved a layout keep their theme's hard-coded order:
  ``resolve_section_layout`` reports ``custom=False`` and templates emit no
  ordering/hiding CSS at all.
- Theme-category references are normalized via ``normalize_category`` (lower-
  cased, spaces/dashes to underscores) so callers may pass the raw display
  name ("Video Editor") or the canonical key ("video_editor") interchangeably.
"""


def normalize_category(category):
    """Normalize a theme-category reference to its canonical slug key.

    Accepts the DB display name ("Video Editor"), the slug ("video_editor"),
    or any mixed/None value, and returns a stable key used in the lookups
    below. An unusable value yields ``''`` so lookups resolve to the
    video-editor defaults (the longest / most complete family).
    """
    if not category:
        return ''
    return str(category).lower().strip().replace(' ', '_').replace('-', '_')


def _theme_slug(theme):
    """Normalize a theme name/reference to its slug ('minimal', 'categories')."""
    if not theme:
        return ''
    return str(theme).lower().strip().replace(' ', '_').replace('-', '_')


def profile_theme_slug(profile):
    """Normalized theme slug of a profile's theme, or '' when unset."""
    return _theme_slug(getattr(getattr(profile, 'theme', None), 'name', None))


def section_layout_supported(category, theme=None):
    """True when the theme's public template ships the layout panel + CSS."""
    return (normalize_category(category), _theme_slug(theme)) in LAYOUT_ENABLED_THEMES

SECTION_KEYS = ['projects', 'skills', 'experience', 'education', 'reviews', 'creators', 'links', 'contact']

# Sections each theme family can actually render. Anything not listed is
# hidden from the builder panel and ignored at render time. The video_editor
# order follows the creative theme's sequence (the family's canonical look);
# video_editor_minimal's DOM is kept in the same order so the unsaved default
# renders identically.
CATEGORY_SECTION_SUPPORT = {
    'video_editor': ['projects', 'skills', 'experience', 'education', 'creators', 'reviews', 'links', 'contact'],
    'developer': ['projects', 'skills', 'experience', 'education', 'links'],
    'student': ['education', 'skills', 'experience', 'projects', 'links'],
}

# Family fallback when nothing is saved — serves themes without their own
# THEME_SECTION_DEFAULTS entry (minimal, and any theme without the panel).
# The video_editor sequence follows creative's, with 'links' slotted before
# 'contact' because minimal renders a dedicated links section.
SECTION_ORDER_DEFAULTS = {
    'video_editor': ['projects', 'skills', 'experience', 'education', 'creators', 'reviews', 'links', 'contact'],
    'developer': ['projects', 'skills', 'experience', 'education', 'links'],
    'student': ['education', 'skills', 'experience', 'projects', 'links'],
}

# Per-theme overrides for themes whose supported sections or visual order
# differ from their family default. Keyed by (category, theme) slugs; each
# list is BOTH the supported set and the hard-coded DOM order.
# - creative: the family's canonical sequence, but no dedicated links
#   section (social links live inside its contact section).
# - categories: collections grid first, creators second, no links section.
# - creative_white / animated_dark / yellow / cyan / monochrome: creators
#   right after the hero, no links section. Monochrome renders creators as
#   a trust grid (no marquee).
# - cinematic: no reviews section (6 keys) and its collections grid is
#   id="work".
# - pro: a landing-page layout — hero with CTA cards, then creators,
#   reviews, contact (3 keys).
# - editorial_studio: no skills section (6 keys).
THEME_SECTION_DEFAULTS = {
    ('video_editor', 'creative'): [
        'projects', 'skills', 'experience', 'education', 'creators', 'reviews', 'contact',
    ],
    ('video_editor', 'categories'): [
        'projects', 'creators', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'creative_white'): [
        'creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'animated_dark'): [
        'creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'monochrome'): [
        'creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'animated'): [
        'creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'yellow'): [
        'creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'cyan'): [
        'creators', 'projects', 'skills', 'experience', 'education', 'reviews', 'contact',
    ],
    ('video_editor', 'cinematic'): [
        'projects', 'skills', 'experience', 'education', 'creators', 'contact',
    ],
    ('video_editor', 'pro'): [
        'creators', 'reviews', 'contact',
    ],
    ('video_editor', 'editorial_studio'): [
        'projects', 'experience', 'education', 'creators', 'reviews', 'contact',
    ],
}

# (category, theme) pairs whose public template ships the section-layout
# panel and includes portfolios/common/section_layout_css.html.
LAYOUT_ENABLED_THEMES = {
    ('video_editor', 'minimal'),
    ('video_editor', 'creative'),
    ('video_editor', 'categories'),
    ('video_editor', 'creative_white'),
    ('video_editor', 'animated_dark'),
    ('video_editor', 'monochrome'),
    ('video_editor', 'animated'),
    ('video_editor', 'yellow'),
    ('video_editor', 'cyan'),
    ('video_editor', 'cinematic'),
    ('video_editor', 'pro'),
    ('video_editor', 'editorial_studio'),
}

DEFAULT_SECTION_ORDER = list(SECTION_ORDER_DEFAULTS['video_editor'])

# Candidate CSS selectors per key (superset across families). Order rules and
# display:none rules simply no-op on themes where a selector doesn't exist.
# Creators covers both the heading section and its marquee so they move and
# hide together.
SECTION_META = {
    'projects': {'label': 'Work Showcase', 'label_ar': 'معرض الأعمال', 'icon': '▶',
                 'selectors': ['#portfolio', '#projects', '#work', '.stats-block']},
    'skills': {'label': 'Software Skills', 'label_ar': 'المهارات', 'icon': '⚡',
               'selectors': ['#skills']},
    'experience': {'label': 'Work Experience', 'label_ar': 'الخبرات العملية', 'icon': '📋',
                   'selectors': ['#experience']},
    'education': {'label': 'Education', 'label_ar': 'التعليم', 'icon': '🎓',
                  'selectors': ['#education']},
    'reviews': {'label': 'Client Reviews', 'label_ar': 'آراء العملاء', 'icon': '⭐',
                'selectors': ['#reviews']},
    'creators': {'label': 'Creators & Inspiration', 'label_ar': 'المبدعون والإلهام', 'icon': '✨',
                 'selectors': ['#creators', '.creators-marquee-container']},
    'links': {'label': 'Social Links', 'label_ar': 'روابط التواصل', 'icon': '🔗',
              'selectors': ['#connect', '#links']},
    'contact': {'label': 'Contact CTA', 'label_ar': 'قسم التواصل', 'icon': '✉️',
                'selectors': ['#contact']},
}

CATEGORY_LABEL_OVERRIDES = {
    'student': {
        'projects': {'label': 'Academic Projects', 'label_ar': 'المشاريع الأكاديمية', 'icon': '📁'},
        'skills': {'label': 'Expertise', 'label_ar': 'الخبرة', 'icon': '⚡'},
    },
    'developer': {
        'projects': {'label': 'Projects', 'label_ar': 'المشاريع', 'icon': '▶'},
        'skills': {'label': 'Expertise', 'label_ar': 'الخبرة', 'icon': '⚡'},
    },
}

# One-click storytelling presets offered in the builder panel. Values are key
# orders; unsupported keys are filtered out per category at use time.
SECTION_PRESETS = {
    'recruiter_first': ['projects', 'skills', 'experience', 'education', 'reviews', 'creators', 'links', 'contact'],
    'client_first': ['projects', 'reviews', 'skills', 'experience', 'links', 'creators', 'education', 'contact'],
    'social_proof_first': ['reviews', 'creators', 'projects', 'skills', 'experience', 'education', 'links', 'contact'],
}

PRESET_LABELS = {
    'recruiter_first': {'label': 'Recruiter first', 'label_ar': 'مسؤول التوظيف أولًا'},
    'client_first': {'label': 'Client first', 'label_ar': 'العميل أولًا'},
    'social_proof_first': {'label': 'Social proof first', 'label_ar': 'الإثبات الاجتماعي أولًا'},
}


def supported_keys(category, theme=None):
    """Return the section keys the given theme can render, in default order.

    Theme-specific overrides (``THEME_SECTION_DEFAULTS``) win; otherwise the
    family defaults apply.
    """
    category = normalize_category(category)
    theme_defaults = THEME_SECTION_DEFAULTS.get((category, _theme_slug(theme)))
    if theme_defaults is not None:
        return list(theme_defaults)
    defaults = SECTION_ORDER_DEFAULTS.get(category)
    if defaults is None:
        return list(DEFAULT_SECTION_ORDER)
    support = CATEGORY_SECTION_SUPPORT.get(category)
    if support is None:
        support = [k for k in defaults if k in SECTION_KEYS]
    return [k for k in defaults if k in support]


def get_section_meta(category, theme=None):
    """Return ordered metadata dicts for the builder UI, theme-aware."""
    overrides = CATEGORY_LABEL_OVERRIDES.get(normalize_category(category), {})
    meta_rows = []
    for key in supported_keys(category, theme):
        base = SECTION_META[key]
        row = overrides.get(key) or base
        meta_rows.append({
            'key': key,
            'label': row.get('label', base['label']),
            'label_ar': row.get('label_ar', base['label_ar']),
            'icon': row.get('icon', base['icon']),
        })
    return meta_rows


def presets_for(category, theme=None):
    """Return builder-ready preset rows: key, labels, and theme-filtered order."""
    supported = supported_keys(category, theme)
    rows = []
    for key, order in SECTION_PRESETS.items():
        filtered = [k for k in order if k in supported]
        if len(filtered) < 2:
            continue
        labels = PRESET_LABELS[key]
        rows.append({
            'key': key,
            'label': labels['label'],
            'label_ar': labels['label_ar'],
            'order': filtered,
        })
    return rows


def _coerce_order_candidates(raw):
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(',')]
    if isinstance(raw, (list, tuple)):
        return [str(part).strip().lower() for part in raw]
    return []


def normalize_section_order(raw, category=None, theme=None):
    """Sanitize a raw order value (comma string or list) into a valid list.

    - Drops unknown keys and duplicates.
    - Appends any missing supported keys at the end so every section stays
      reachable (new sections introduced later show up automatically).
    - Returns the theme's default when nothing valid is supplied.
    """
    category = normalize_category(category)
    seen = set()
    order_list = []
    allowed = set(SECTION_KEYS)
    for key in _coerce_order_candidates(raw):
        if key in allowed and key not in seen:
            seen.add(key)
            order_list.append(key)

    supported = supported_keys(category, theme)
    if not order_list:
        return list(supported)

    # Keep only keys this theme family supports, then append missing ones.
    order_list = [key for key in order_list if key in supported]
    for key in supported:
        if key not in order_list:
            order_list.append(key)
    return order_list


def normalize_section_visibility(raw, category=None, theme=None):
    """Sanitize a visibility map (JSON string or dict) into {key: bool}.

    Unknown keys are dropped; values are coerced to real booleans; keys not
    present in the input default to True downstream (partial overrides).
    """
    category = normalize_category(category)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        import json
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}

    supported = set(supported_keys(category, theme))
    result = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            key = str(key).strip().lower()
            if key in supported:
                result[key] = bool(value)
    return result


def resolve_section_layout(profile, category=None, theme=None):
    """Resolve the full layout to render for a profile.

    When ``theme`` is not given it is derived from ``profile.theme.name``, so
    callers only need the profile and the theme-category. Returns a dict
    consumed by portfolio templates and tests::

        {
            'custom': bool,       # False -> emit no layout CSS at all
            'sections': [         # resolved final order
                {'key', 'label', 'label_ar', 'icon', 'visible',
                 'selectors': [...], 'hrefs': [...]}
            ],
            'order_keys': [...],  # visible+hidden keys, resolved order
            'hidden_keys': [...],
            'default_order': [...],
        }
    """
    category = normalize_category(category) or None
    if theme is None:
        theme = profile_theme_slug(profile)
    default_order = supported_keys(category, theme)
    saved_order = getattr(profile, 'section_order', None) or []
    saved_visibility = getattr(profile, 'section_visibility', None) or {}

    order_keys = normalize_section_order(saved_order, category, theme)
    hidden = {key for key, value in normalize_section_visibility(saved_visibility, category, theme).items() if value is False}
    custom = bool(saved_order) or bool(hidden)

    sections = []
    for key in order_keys:
        meta = SECTION_META[key]
        selectors = list(meta['selectors'])
        sections.append({
            'key': key,
            'label': meta['label'],
            'label_ar': meta['label_ar'],
            'icon': meta['icon'],
            'visible': key not in hidden,
            'selectors': selectors,
            'hrefs': [sel.lstrip('#') for sel in selectors if sel.startswith('#')],
        })

    return {
        'custom': custom,
        'sections': sections,
        'order_keys': order_keys,
        'hidden_keys': [key for key in order_keys if key in hidden],
        'default_order': list(default_order),
    }


def effective_section_order(profile, category):
    """Backward-compatible helper: resolved order keys, [] when nothing saved."""
    layout = resolve_section_layout(profile, category)
    return layout['order_keys'] if layout['custom'] else []
