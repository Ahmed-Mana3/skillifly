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
"""

SECTION_KEYS = ['projects', 'skills', 'experience', 'education', 'reviews', 'creators', 'links', 'contact']

# Sections each theme family can actually render. Anything not listed is
# hidden from the builder panel and ignored at render time.
CATEGORY_SECTION_SUPPORT = {
    'video_editor': ['projects', 'skills', 'experience', 'reviews', 'creators', 'education', 'links', 'contact'],
    'developer': ['projects', 'skills', 'experience', 'education', 'links'],
    'student': ['education', 'skills', 'experience', 'projects', 'links'],
}

# Mirrors each family's hard-coded visual order (fallback when nothing saved).
SECTION_ORDER_DEFAULTS = {
    'video_editor': ['projects', 'skills', 'experience', 'reviews', 'creators', 'education', 'links', 'contact'],
    'developer': ['projects', 'skills', 'experience', 'education', 'links'],
    'student': ['education', 'skills', 'experience', 'projects', 'links'],
}

DEFAULT_SECTION_ORDER = list(SECTION_ORDER_DEFAULTS['video_editor'])

# Candidate CSS selectors per key (superset across families). Order rules and
# display:none rules simply no-op on themes where a selector doesn't exist.
# Creators includes the marquee wrappers so heading + marquee move together.
SECTION_META = {
    'projects': {'label': 'Work Showcase', 'label_ar': 'معرض الأعمال', 'icon': '▶',
                 'selectors': ['#portfolio', '#projects', '#work']},
    'skills': {'label': 'Software Skills', 'label_ar': 'المهارات', 'icon': '⚡',
               'selectors': ['#skills']},
    'experience': {'label': 'Work Experience', 'label_ar': 'الخبرات العملية', 'icon': '📋',
                   'selectors': ['#experience']},
    'education': {'label': 'Education', 'label_ar': 'التعليم', 'icon': '🎓',
                  'selectors': ['#education']},
    'reviews': {'label': 'Client Reviews', 'label_ar': 'آراء العملاء', 'icon': '⭐',
                'selectors': ['#reviews']},
    'creators': {'label': 'Creators & Inspiration', 'label_ar': 'المبدعون والإلهام', 'icon': '✨',
                 'selectors': ['#creators', '.creators-marquee-container', '.marquee-wrap', '.marquee-strip']},
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


def supported_keys(category):
    """Return the section keys the given theme family can render, in default order."""
    defaults = SECTION_ORDER_DEFAULTS.get(category)
    if defaults is None:
        return list(DEFAULT_SECTION_ORDER)
    support = CATEGORY_SECTION_SUPPORT.get(category)
    if support is None:
        support = [k for k in defaults if k in SECTION_KEYS]
    return [k for k in defaults if k in support]


def get_section_meta(category):
    """Return ordered metadata dicts for the builder UI, category-aware."""
    overrides = CATEGORY_LABEL_OVERRIDES.get(category, {})
    meta_rows = []
    for key in supported_keys(category):
        base = SECTION_META[key]
        row = overrides.get(key) or base
        meta_rows.append({
            'key': key,
            'label': row.get('label', base['label']),
            'label_ar': row.get('label_ar', base['label_ar']),
            'icon': row.get('icon', base['icon']),
        })
    return meta_rows


def _coerce_order_candidates(raw):
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(',')]
    if isinstance(raw, (list, tuple)):
        return [str(part).strip().lower() for part in raw]
    return []


def normalize_section_order(raw, category=None):
    """Sanitize a raw order value (comma string or list) into a valid list.

    - Drops unknown keys and duplicates.
    - Appends any missing supported keys at the end so every section stays
      reachable (new sections introduced later show up automatically).
    - Returns the category default when nothing valid is supplied.
    """
    seen = set()
    order_list = []
    allowed = set(SECTION_KEYS)
    for key in _coerce_order_candidates(raw):
        if key in allowed and key not in seen:
            seen.add(key)
            order_list.append(key)

    supported = supported_keys(category)
    if not order_list:
        return list(supported)

    # Keep only keys this theme family supports, then append missing ones.
    order_list = [key for key in order_list if key in supported]
    for key in supported:
        if key not in order_list:
            order_list.append(key)
    return order_list


def normalize_section_visibility(raw, category=None):
    """Sanitize a visibility map (JSON string or dict) into {key: bool}.

    Unknown keys are dropped; values are coerced to real booleans; keys not
    present in the input default to True downstream (partial overrides).
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        import json
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}

    supported = set(supported_keys(category))
    result = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            key = str(key).strip().lower()
            if key in supported:
                result[key] = bool(value)
    return result


def resolve_section_layout(profile, category=None):
    """Resolve the full layout to render for a profile.

    Returns a dict consumed by portfolio templates and tests::

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
    category = (category or '').lower() or None
    default_order = supported_keys(category)
    saved_order = getattr(profile, 'section_order', None) or []
    saved_visibility = getattr(profile, 'section_visibility', None) or {}

    order_keys = normalize_section_order(saved_order, category)
    hidden = {key for key, value in normalize_section_visibility(saved_visibility, category).items() if value is False}
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
