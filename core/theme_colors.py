"""Per-theme background *and* accent colour customisation.

Single source of truth for the two colour options offered on the
Customize-your-theme page: which themes support them, what each theme's own
shipped colours are, the curated preset palettes, POST sanitization, and the
contrast-aware derivation that keeps a supported theme legible on any colour
a user picks.

Design notes
------------
- Storage follows the ``Profile.section_*`` convention: a JSONField
  (``Profile.theme_settings``) holding ``{"background": "#0A0E27"}`` and/or
  ``{"accent": "#10B981"}``. A profile that never customised anything stores
  ``{}``, which means "use the theme's own colours" and keeps the rendered
  page byte-identical to before. Because one colour is stored per profile
  rather than per theme, a user who picks a tone on one theme keeps it when
  they switch to another supported theme — and because the gate is re-checked
  on read, a theme that is not in the registry never renders the override.
- Only themes listed in :data:`BACKGROUND_ENABLED_THEMES` may be recoloured.
  The gate is enforced in three places — the option card on the customize
  page, the editor page itself, and the AJAX save endpoint — so a crafted
  POST cannot colour a theme that does not ship the override block.
  ``ThemeBackgroundTemplateTests`` guards the invariant that every enabled
  theme's public templates really do ship the override.
- The enabled themes group into six CSS token *families* (see
  :data:`THEME_BACKGROUND_SPECS`). A single custom property override cannot
  serve all of them: ``minimal`` names its background ``--bg-dark``, the
  editorial theme names it ``--paper``, the neo-brutalist themes pair it with
  hard black borders and offset shadows, a fourth group (Animated, Animated
  Dark, Creative, Creative White) writes its chrome as literals tuned to one
  polarity, Developer Classic paints a Tailwind page out of ``--sfc-*`` tokens
  with an accent-filled hero, and the rest use ``--bg``/``--surface``. The
  stylesheet partial bridges the derived ``--sf-*`` tokens into whichever
  vocabulary the rendered theme uses, so this module only has to describe
  *what* a theme looks like, not *how* it spells it.
- A free-form colour picker would happily produce a white page with white
  text, so the chosen background drives a *derived* palette (surfaces, text,
  borders, glassy nav) computed from WCAG relative luminance. Text and
  ``hard_ink`` flip with the background's polarity, which is what makes the
  neo-brutalist themes survive a light pick and a dark one alike.
- The **accent** is the theme's brand colour — the emerald of Categories, the
  cyan of Minimal, the ember of Editorial Studio. It is stored beside the
  background in the same JSONField and travels with it, because the two are
  picked together and a green accent on a black page is exactly the look the
  user is buying. Accent picks get the same treatment as backgrounds but
  against the *accent's own* job: it is mostly large display type and link
  colour sitting on the background, so
  :func:`derive_accent_palette` guarantees it clears WCAG AA against whatever
  background is in force, and derives the partner/soft/glow tones and the
  ``accent_ink`` used for text on top of an accent fill.
- Accent tokens are described per theme as a slot -> CSS-property mapping
  (``accent_tokens``) rather than a flat list, because the thirteen themes
  spell the same idea five different ways: Categories has
  ``--accent``/``--accent-glow``/``--accent-light`` and a composed
  ``--grad``; Animated has ``--accent-1/2/3``; Minimal calls it
  ``--primary``; Editorial Studio calls it ``--ember``; and the
  neo-brutalist themes have no accent of their own at all — there the accent
  *is* the hard ink, so the control is disabled rather than faked.
- ``derive_palette`` / ``derive_accent_palette`` are mirrored (deliberately,
  and only for the instant preview) by ``derive()`` in
  ``templates/dashboard/customize_background.html``. The server copy is
  authoritative; keep the two in step when tuning either.
"""

from core.section_order import normalize_category

import colorsys
import re

# Fallback background used when a theme is not in the registry (and as the
# value ``derive_palette`` falls back to for an unparseable pick). Matches the
# Minimal theme's shipped navy so behaviour is unchanged for it.
DEFAULT_BACKGROUND = '#0A0E27'

# How a theme spells its background tokens. The stylesheet partial emits a
# different bridge per family.
#
#   surface  --bg / --surface / --glass / --text / --border  (most themes)
#   glass    --bg / --surface / --glass, plus a chrome layer written as
#             literals for the theme's own polarity (Animated, Animated Dark,
#             Creative, Creative White)
#   minimal  --bg-dark / --bg-card / --text-primary  (Minimal)
#   paper    --paper / --paper-strong / --ink / --line  (Editorial Studio)
#   brutal   --bg + hard borders and offset shadows  (Cyan, Yellow, Monochrome)
#   classic  --sfc-* tokens over a Tailwind page: Developer Classic paints its
#             ink as a near-black navy and its brand as a deep blue, and the
#             hero is a *filled* accent block whose type has to invert with the
#             accent's polarity rather than with the background's.
FAMILY_SURFACE = 'surface'
FAMILY_GLASS = 'glass'
FAMILY_MINIMAL = 'minimal'
FAMILY_PAPER = 'paper'
FAMILY_BRUTAL = 'brutal'
FAMILY_CLASSIC = 'classic'

# Slots a theme's accent token map can fill. The stylesheet partial reads these
# names, so a slot added here needs a matching branch there.
#
#   primary   the brand colour itself — headings, links, active states
#   partner   the second stop of a gradient / the hover tone
#   soft      a low-alpha wash of the accent (tinted fills, glow backdrops)
#   glow      the brighter "lit" tone used for ring/glow effects
#   trio      the third hue of a triadic set — ambient orbs, badges, "long
#             form" chips — so a recolour never leaves the shipped third
#             colour stranded next to the new brand colour
#   ink       the text colour that sits *on top of* a filled accent surface
SLOT_PRIMARY = 'primary'
SLOT_PARTNER = 'partner'
SLOT_SOFT = 'soft'
SLOT_GLOW = 'glow'
SLOT_TRIO = 'trio'
SLOT_INK = 'ink'

# Per-theme description of the recolour features, keyed by
# ``(normalized category, normalized theme slug)``.
#
#   default    the background the theme ships with — what "Reset" returns to and
#              what the editor pre-selects. Not every theme's default is dark, so
#              this cannot be a single module constant any more.
#   family     which CSS token vocabulary templates/portfolios/common/
#              theme_background_css.html bridges the derived tokens into.
#   accent     the theme's brand colour, surfaced in the editor's live preview so
#              the mock-up looks like the user's actual site.
#   gradient   the theme's own heading gradient, used for the same reason.
#   accent_tokens
#              the CSS custom properties that carry the accent, per slot. A
#              theme with an empty map has no recolourable accent — the
#              neo-brutalist family, whose accent is its hard ink and already
#              follows the background.
#   accent_channels
#              the CSS custom properties that carry each tone as *bare RGB
#              channels* ("255, 61, 107", no rgb() wrapper), per slot. A theme
#              only lists these if it fades its own accent with
#              ``rgba(var(--accent-rgb), .08)`` rather than through a token;
#              Creative does, in roughly forty places, and those all have to
#              move with the accent or a recoloured page reads as a repaint
#              with the old brand colour still showing through.
#   polarity   ``dark`` when the shipped default is dark. Only a hint: the real
#              polarity of any pick comes from WCAG luminance in
#              :func:`derive_palette`, so a light pick on a dark theme is fine.
VIDEO_EDITOR_CATEGORY = 'video_editor'
DEVELOPER_CATEGORY = 'developer'

# Display names for the registry's category keys. Used by the locked panel to
# name the categories that *do* support colours, so the copy can never claim a
# capability the gate does not have.
CATEGORY_LABELS = {
    VIDEO_EDITOR_CATEGORY: 'Video Editor',
    DEVELOPER_CATEGORY: 'Developer',
}

# Editorial Studio's ink palette: the accent is the "ember", and the other three
# stay put so a recolour reads as one changed brand colour rather than a
# four-hue repaint.
_PAPER_ACCENT_TOKENS = {SLOT_PRIMARY: ('--ember',)}

THEME_BACKGROUND_SPECS = {
    ('video_editor', 'minimal'): {
        'default': '#0A0E27',
        'family': FAMILY_MINIMAL,
        'accent': '#00D9FF',
        'gradient': ('#00D9FF', '#FFFFFF', '#FF006E'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--primary', '--accent'),
            SLOT_PARTNER: ('--primary-dark',),
            SLOT_SOFT: ('--primary-glow',),
        },
    },
    ('video_editor', 'pro'): {
        'default': '#000000',
        'family': FAMILY_SURFACE,
        'accent': '#00D9FF',
        'gradient': ('#00D9FF', '#00D9FF', '#0099CC'),
        'accent_tokens': {SLOT_PRIMARY: ('--accent',)},
        # Pro is the other theme that fades its brand colour as a literal rather
        # than through a token: the hero bloom, both card hover washes, the icon
        # tile, the social/creator chip hovers, the review avatar ring, the star
        # rings and the footer's hairline. All of them move to --accent-rgb.
        'accent_channels': {
            SLOT_PRIMARY: ('--accent-rgb',),
        },
    },
    ('video_editor', 'creative'): {
        'default': '#04040A',
        'family': FAMILY_GLASS,
        'accent': '#FF3D6B',
        'gradient': ('#FF3D6B', '#FF8C00', '#FFD700'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent',),
            SLOT_PARTNER: ('--accent2',),
            SLOT_TRIO: ('--gold',),
        },
        # The theme fades its own brand colour directly — hover washes, card
        # glows, pill fills, the ambient orbs, the placeholder gradients on
        # canvas — so the colour also has to be reachable as bare channels.
        'accent_channels': {
            SLOT_PRIMARY: ('--accent-rgb',),
            SLOT_PARTNER: ('--accent2-rgb',),
            SLOT_TRIO: ('--gold-rgb',),
        },
    },
    ('video_editor', 'creative_white'): {
        'default': '#F8F7F4',
        'family': FAMILY_GLASS,
        'accent': '#6C3CE0',
        'gradient': ('#6C3CE0', '#D2346A', '#BD5A10'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent',),
            SLOT_PARTNER: ('--accent2',),
            SLOT_SOFT: ('--accent3',),
        },
    },
    ('video_editor', 'animated'): {
        'default': '#F3F7FA',
        'family': FAMILY_GLASS,
        'accent': '#00C9FF',
        'gradient': ('#FF3366', '#00C9FF', '#20E3B2'),
        'accent_tokens': {
            # The main page inherits animated.css's --accent-1/2/3, but the
            # light reels/long templates carry their own :root that spells the
            # same brand colour --accent. Both have to be bridged or the
            # subpages keep the old hue.
            SLOT_PRIMARY: ('--accent-1', '--accent'),
            SLOT_PARTNER: ('--accent-3',),
            SLOT_SOFT: ('--accent-2',),
        },
    },
    ('video_editor', 'animated_dark'): {
        'default': '#0A0A0A',
        'family': FAMILY_GLASS,
        'accent': '#00C9FF',
        'gradient': ('#FF3366', '#00C9FF', '#20E3B2'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent-1', '--accent'),
            SLOT_PARTNER: ('--accent-3',),
            SLOT_SOFT: ('--accent-2',),
        },
    },
    ('video_editor', 'cinematic'): {
        'default': '#03020A',
        'family': FAMILY_SURFACE,
        'accent': '#7C3AED',
        'gradient': ('#7C3AED', '#A78BFA', '#F59E0B'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent',),
            SLOT_PARTNER: ('--accent2',),
            SLOT_GLOW: ('--accent-glow',),
        },
    },
    ('video_editor', 'categories'): {
        'default': '#070E0A',
        'family': FAMILY_SURFACE,
        'accent': '#10B981',
        'gradient': ('#10B981', '#05FF8D', '#10B981'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent',),
            SLOT_PARTNER: ('--accent-glow',),
            SLOT_SOFT: ('--accent-light',),
        },
    },
    ('video_editor', 'categories_white'): {
        'default': '#F8FAFC',
        'family': FAMILY_SURFACE,
        'accent': '#10B981',
        'gradient': ('#10B981', '#059669', '#10B981'),
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent',),
            SLOT_PARTNER: ('--accent-glow',),
            SLOT_SOFT: ('--accent-light',),
        },
    },
    ('video_editor', 'editorial_studio'): {
        'default': '#F5F0E8',
        'family': FAMILY_PAPER,
        'accent': '#FF5A3C',
        'gradient': ('#FF5A3C', '#0F9F9A', '#6C4CC4'),
        'accent_tokens': dict(_PAPER_ACCENT_TOKENS),
    },
    ('video_editor', 'kinetic'): {
        'default': '#F7F6F2',
        'family': FAMILY_SURFACE,
        'accent': '#7C3AED',
        'gradient': ('#7C3AED', '#4F46E5', '#DB2777'),
        # Kinetic wears the landing page's brand purple/indigo/pink and fades every
        # tone with rgba(var(--accent*-rgb), a) — auroras, glows, chip washes,
        # card hover rings — so the channels travel with the tokens.
        'accent_tokens': {
            SLOT_PRIMARY: ('--accent',),
            SLOT_PARTNER: ('--accent2',),
            SLOT_TRIO: ('--accent3',),
        },
        'accent_channels': {
            SLOT_PRIMARY: ('--accent-rgb',),
            SLOT_PARTNER: ('--accent2-rgb',),
            SLOT_TRIO: ('--accent3-rgb',),
        },
    },
    ('video_editor', 'cyan'): {
        'default': '#00E5FF',
        'family': FAMILY_BRUTAL,
        'accent': '#000000',
        'gradient': ('#000000', '#000000', '#000000'),
        # No accent of its own: the black is the border, the shadow and the
        # type, all of which already travel with the background's polarity.
        'accent_tokens': {},
    },
    ('video_editor', 'yellow'): {
        'default': '#FFE600',
        'family': FAMILY_BRUTAL,
        'accent': '#000000',
        'gradient': ('#000000', '#000000', '#000000'),
        'accent_tokens': {},
    },
    ('video_editor', 'monochrome'): {
        'default': '#FFFFFF',
        'family': FAMILY_BRUTAL,
        'accent': '#000000',
        'gradient': ('#000000', '#000000', '#000000'),
        'accent_tokens': {},
    },
    ('developer', 'classic'): {
        'default': '#F9FAFB',
        'family': FAMILY_CLASSIC,
        'accent': '#1E3A8A',
        'gradient': ('#1E3A8A', '#1D4ED8', '#0F172A'),
        # The theme spells every colour as a --sfc-* token, so a recolour is a
        # straight repoint: the brand blue that fills the hero, draws the section
        # rules and underlines every project link is ``primary``; the deeper
        # shade on the education spine and the hover borders is ``partner``; and
        # the pale wash behind the skill pills and the date chips is ``soft``.
        # The type printed on top of the accent-filled hero is not listed here
        # because it is not a fixed colour: it answers to the derived ``ink``
        # tone, which the stylesheet reads straight off ``--sf-accent-ink``.
        'accent_tokens': {
            SLOT_PRIMARY: ('--sfc-accent',),
            SLOT_PARTNER: ('--sfc-accent-strong',),
            SLOT_SOFT: ('--sfc-accent-wash',),
        },
        # The footer's brand card tints its lift and hover shadows with the brand
        # colour at 8% / 12%, which no token can express.
        'accent_channels': {
            SLOT_PRIMARY: ('--sfc-accent-rgb',),
        },
    },
}

# (category, theme) pairs whose public template includes
# portfolios/common/theme_background_css.html and therefore honours
# ``Profile.theme_settings['background']``. Derived from the registry so the
# gate can never drift from the theme descriptions it is built on.
BACKGROUND_ENABLED_THEMES = frozenset(THEME_BACKGROUND_SPECS)

# Curated swatches offered before the free-form picker, appended after the
# theme's own default. Deliberately neutral enough to sit under any accent:
# six deep tones, two paper tones, then the theme default so "back to how it
# looked" is one click away even if it fell off the end of the grid.
NEUTRAL_BACKGROUND_PRESETS = [
    {'value': '#0A0A0A', 'label': 'Ink', 'label_ar': 'حبر'},
    {'value': '#151522', 'label': 'Graphite', 'label_ar': 'جرافيت'},
    {'value': '#1E1B4B', 'label': 'Indigo', 'label_ar': 'نيلي'},
    {'value': '#2B1055', 'label': 'Violet', 'label_ar': 'بنفسجي'},
    {'value': '#0B2B26', 'label': 'Forest', 'label_ar': 'أخضر داكن'},
    {'value': '#0F172A', 'label': 'Slate', 'label_ar': 'إردوازي'},
    {'value': '#1C1917', 'label': 'Espresso', 'label_ar': 'بنّي داكن'},
    {'value': '#F4F2ED', 'label': 'Sand', 'label_ar': 'رملي'},
    {'value': '#FFFFFF', 'label': 'Cloud', 'label_ar': 'أبيض'},
]

# Human label for the theme's own default swatch. Kept generic because the
# label has to read correctly next to thirteen different themes.
DEFAULT_PRESET = {'value': DEFAULT_BACKGROUND, 'label': 'Theme default', 'label_ar': 'افتراضي الثيم'}

# Curated accent swatches, offered before the free-form picker. Deliberately
# spread across the hue wheel and across lightness, because an accent is used
# as *type* on the background: a pastel on a white page and a near-black on a
# black page are both unusable, and the user should not have to discover that
# by looking at a live site. The theme's own accent leads the grid.
NEUTRAL_ACCENT_PRESETS = [
    {'value': '#10B981', 'label': 'Emerald', 'label_ar': 'زمردي'},
    {'value': '#00D9FF', 'label': 'Cyan', 'label_ar': 'سماوي'},
    {'value': '#7C3AED', 'label': 'Violet', 'label_ar': 'بنفسجي'},
    {'value': '#FF3D6B', 'label': 'Rose', 'label_ar': 'وردي'},
    {'value': '#F59E0B', 'label': 'Amber', 'label_ar': 'كهرماني'},
    {'value': '#FF5A3C', 'label': 'Ember', 'label_ar': 'جمر'},
    {'value': '#0EA5E9', 'label': 'Sky', 'label_ar': 'سماوي فاتح'},
    {'value': '#E8457C', 'label': 'Magenta', 'label_ar': 'أرجواني'},
    {'value': '#F5A623', 'label': 'Gold', 'label_ar': 'ذهبي'},
    {'value': '#6C3CE0', 'label': 'Iris', 'label_ar': 'بنفسجي داكن'},
    {'value': '#2DD4BF', 'label': 'Aqua', 'label_ar': 'فيروزي'},
    {'value': '#F43F5E', 'label': 'Crimson', 'label_ar': 'قرمزي'},
]

# Human label for the theme's own accent swatch.
DEFAULT_ACCENT_PRESET = {'value': DEFAULT_BACKGROUND, 'label': 'Theme default', 'label_ar': 'افتراضي الثيم'}

# Accent type is large (headings, stat figures, section labels), so WCAG AA
# Large — 3.0:1 — is the floor for the accent against the background, not the
# 4.5:1 that body copy needs. The derived `ink` tone (text on a filled accent
# button) is held to the full 4.5:1 because button labels are small.
ACCENT_MIN_CONTRAST = 3.0
ACCENT_INK_MIN_CONTRAST = 4.5

# How far around the colour wheel the third accent tone sits, as a fraction of
# a turn. 0.16 is ~58 degrees, short of a true 120-degree triad: a full triad
# puts the third hue opposite the accent, which on a dark page is a cold blue
# fighting a warm brand colour. Short of it, the set stays one family.
TRIO_HUE_SHIFT = 0.16

# Used when the accent has no hue to rotate (a near-grey pick), so the third
# stop is a colour rather than a third shade of the same grey.
TRIO_FALLBACK = '#FFD700'

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
# The Minimal theme's on-accent navy, used as the darkest "ink" tone and as the
# body-text colour on a light pick.
ACCENT_INK = (10, 14, 39)

# Six hex digits, nothing else — the storage format is deliberately narrow so a
# stored value can be dropped straight into a CSS declaration.
_HEX_RE = re.compile(r'^[0-9a-fA-F]{6}$')


def profile_category_slug(profile):
    """Normalized theme-category slug of a profile's theme, or '' when unset."""
    theme = getattr(profile, 'theme', None)
    category = getattr(theme, 'category', None)
    return normalize_category(getattr(category, 'name', None))


def _theme_slug(theme):
    """Normalized slug of a theme name/reference ('minimal')."""
    if not theme:
        return ''
    return str(theme).lower().strip().replace(' ', '_').replace('-', '_')


def background_color_supported(category, theme=None):
    """True when the theme's public template ships the background override."""
    return (normalize_category(category), _theme_slug(theme)) in BACKGROUND_ENABLED_THEMES


def theme_background_spec(category, theme=None):
    """The registry entry for a ``(category, theme)`` pair, or ``None``.

    ``None`` means "unsupported", which every caller treats the same way.
    """
    return THEME_BACKGROUND_SPECS.get((normalize_category(category), _theme_slug(theme)))


def default_background(category=None, theme=None):
    """The background a theme ships with — what Reset returns to.

    Falls back to :data:`DEFAULT_BACKGROUND` for pairs that are not enabled,
    so a caller can never end up offering "reset" on a colour that is not the
    theme's own.
    """
    spec = theme_background_spec(category, theme)
    if not spec:
        return DEFAULT_BACKGROUND
    return spec['default']


def theme_family(category=None, theme=None):
    """CSS token vocabulary of a theme (:data:`FAMILY_SURFACE` when unknown)."""
    spec = theme_background_spec(category, theme)
    return spec['family'] if spec else FAMILY_SURFACE


def accent_tokens(category=None, theme=None):
    """Slot -> CSS custom properties that carry the theme's accent.

    Empty for an unsupported theme *and* for a supported theme with no
    recolourable accent (the neo-brutalist family), which is what the editor
    uses to decide whether to offer the accent control at all.
    """
    spec = theme_background_spec(category, theme)
    return dict(spec.get('accent_tokens') or {}) if spec else {}


def accent_color_supported(category, theme=None):
    """True when the theme has an accent the user may recolour."""
    return bool(accent_tokens(category, theme))


def accent_channels(category, theme=None):
    """Slot -> CSS custom properties carrying that tone as bare RGB channels.

    Empty for themes that express their accent through tokens only. The
    stylesheet partial turns each entry into ``--accent-rgb: 255, 61, 107;``
    so the theme can write ``rgba(var(--accent-rgb), 0.4)``.
    """
    spec = theme_background_spec(category, theme)
    return dict(spec.get('accent_channels') or {}) if spec else {}


def accent_channel_vars(category, theme, accent_palette):
    """:func:`accent_channels` already resolved against a derived palette.

    Returns ``[{'property': '--accent-rgb', 'channels': '255, 61, 107'}]``,
    which is the shape the stylesheet partial can loop over directly — the
    channel value lives under a per-slot key in the palette, and a template
    cannot build ``'<slot>_rgb'`` as a dict lookup.
    """
    slots = accent_channels(category, theme)
    resolved = []
    for slot, properties in slots.items():
        channels = (accent_palette or {}).get('{}_rgb'.format(slot))
        if not channels:
            continue
        for prop in properties:
            resolved.append({'property': prop, 'channels': channels})
    return resolved


def default_accent(category=None, theme=None):
    """The accent a theme ships with — what Reset returns to.

    Falls back to :data:`DEFAULT_BACKGROUND` for pairs that are not enabled so
    a caller can never offer "reset" on a colour the theme does not use.
    """
    spec = theme_background_spec(category, theme)
    if not spec:
        return DEFAULT_BACKGROUND
    return spec['accent']


def presets_for(category=None, theme=None):
    """The swatch grid shown in the editor, led by the theme's own default.

    Every theme's default is guaranteed to be first — the "theme default" row
    is the answer to "what was it before I touched anything", and it must not
    move around as the user browses themes. An unsupported pair falls back to
    the shared grid so the locked panel can still render a sample.
    """
    default = default_background(category, theme)
    presets = [{'value': default, 'label': DEFAULT_PRESET['label'], 'label_ar': DEFAULT_PRESET['label_ar']}]
    seen = {default}
    for preset in NEUTRAL_BACKGROUND_PRESETS:
        value = normalize_hex_color(preset['value'])
        if value in seen:
            continue
        seen.add(value)
        presets.append({'value': value, 'label': preset['label'], 'label_ar': preset['label_ar']})
    return presets


def supported_categories():
    """``[(slug, label, [theme display names])]`` for the locked panel.

    Derived from the registry, so the "Colours run on X themes" copy can never
    advertise a capability the gate does not have, or miss one it does. Theme
    names come from the registry slug (``editorial_studio`` -> ``Editorial
    Studio``), which is the same string the gallery shows. Categories keep the
    registry's own order rather than an alphabetical one, so the sentence reads
    biggest-first and a newly enabled theme lands where its neighbours already
    are.
    """
    grouped = {}
    for category, theme_slug in THEME_BACKGROUND_SPECS:
        grouped.setdefault(category, []).append(theme_slug.replace('_', ' ').title())
    return [
        (slug, CATEGORY_LABELS.get(slug, slug.replace('_', ' ').title()), sorted(names))
        for slug, names in grouped.items()
    ]


def supported_theme_summary():
    """One-line, human summary of every theme that supports colours.

    Reads as "Video Editor (Animated, Animated Dark, …) and Developer (Classic)"
    — used wherever the feature is described as available, so enabling a theme
    in the registry is enough to make it show up.
    """
    parts = []
    for _slug, label, names in supported_categories():
        parts.append('{} ({})'.format(label, ', '.join(names)))
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]
    return '{} and {}'.format(', '.join(parts[:-1]), parts[-1])


def accent_presets_for(category=None, theme=None):
    """The accent swatch grid, led by the theme's own brand colour.

    Same contract as :func:`presets_for` — the theme's own accent is always
    first so "back to how it looked" is one click away.
    """
    default = normalize_hex_color(default_accent(category, theme))
    presets = [{'value': default, 'label': DEFAULT_ACCENT_PRESET['label'],
                'label_ar': DEFAULT_ACCENT_PRESET['label_ar']}]
    seen = {default}
    for preset in NEUTRAL_ACCENT_PRESETS:
        value = normalize_hex_color(preset['value'])
        if value in seen:
            continue
        seen.add(value)
        presets.append({'value': value, 'label': preset['label'], 'label_ar': preset['label_ar']})
    return presets


def parse_hex_color(value):
    """Return an ``(r, g, b)`` tuple for ``#rgb``/``#rrggbb``, else ``None``.

    Alpha is deliberately rejected: a translucent page background would show
    the theme's noise overlay and any parent background through the layout,
    which reads as a rendering bug rather than a design choice.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip().lstrip('#')
    if len(raw) == 3:
        raw = ''.join(ch * 2 for ch in raw)
    if not _HEX_RE.match(raw):
        return None
    return tuple(int(raw[i:i + 2], 16) for i in range(0, 6, 2))


def normalize_hex_color(value):
    """Canonical ``#RRGGBB`` uppercase form of a colour, or ``None``."""
    rgb = parse_hex_color(value)
    if rgb is None:
        return None
    return to_hex(rgb)


def to_hex(rgb):
    """``(r, g, b)`` -> ``'#RRGGBB'`` with channels clamped and rounded."""
    return '#{:02X}{:02X}{:02X}'.format(*(clamp_channel(c) for c in rgb[:3]))


def rgba(rgb, alpha):
    """``(r, g, b)`` + alpha -> a CSS ``rgba()`` string."""
    r, g, b = (clamp_channel(c) for c in rgb[:3])
    return 'rgba({}, {}, {}, {})'.format(r, g, b, round(float(alpha), 3))


def to_rgb_channels(value):
    """``'#RRGGBB'`` -> ``'255, 61, 107'`` — the custom-property form of rgb().

    A theme that fades its own brand colour writes
    ``rgba(var(--accent-rgb), 0.4)``, which is the only way to keep a hardcoded
    alpha while still following a colour the user can change at runtime.
    """
    rgb = parse_hex_color(value)
    if rgb is None:
        return '0, 0, 0'
    return ', '.join(str(clamp_channel(c)) for c in rgb)


def clamp_channel(value):
    return max(0, min(255, int(round(value))))


def _linearize(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    """WCAG 2.x relative luminance of an ``(r, g, b)`` tuple."""
    r, g, b = (_linearize(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb_a, rgb_b):
    """WCAG contrast ratio between two colours (1.0 - 21.0)."""
    la, lb = relative_luminance(rgb_a), relative_luminance(rgb_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(rgb):
    """True when white text reads better than black text on ``rgb``."""
    return contrast_ratio(rgb, WHITE) >= contrast_ratio(rgb, BLACK)


def mix(base, layer, weight):
    """Blend ``layer`` over ``base``; ``weight`` is the layer's opacity."""
    weight = max(0.0, min(1.0, float(weight)))
    return tuple(base[i] + (layer[i] - base[i]) * weight for i in range(3))


def normalize_theme_settings(raw, category=None, theme=None):
    """Sanitize a submitted background and/or accent into the stored settings.

    Returns ``{}`` when the theme does not support the override. Each colour is
    kept only when it is a plain hex value *and* differs from what the theme
    ships with:

    - a background equal to the theme's own is dropped, because the override
      layer can only paint a flat colour, so storing it would flatten layered
      backgrounds (the editorial theme's gradient, the neo-brutalist themes'
      dot grid) for no gain;
    - an accent equal to the theme's own is dropped for the ordinary reason —
      the theme already renders it, and storing it would pin a colour the
      user has not actually chosen.

    A bare string is treated as ``{"background": value}`` so older callers and
    cached payloads keep working. An unsupported theme can therefore never end
    up with a stored colour of either kind.
    """
    if not background_color_supported(category, theme):
        return {}

    if isinstance(raw, dict):
        submitted = raw
    else:
        submitted = {'background': raw}

    settings = {}
    background = normalize_hex_color(submitted.get('background'))
    if background and background != default_background(category, theme):
        settings['background'] = background

    accent = normalize_hex_color(submitted.get('accent'))
    if (accent and accent_color_supported(category, theme)
            and accent != default_accent(category, theme)):
        settings['accent'] = accent

    return settings


def apply_background_selection(profile, raw, category=None, theme=None):
    """Persist a submitted background pick on ``profile`` and report what changed.

    Returns ``(settings, colour, reset)``. ``settings`` is the value written to
    ``Profile.theme_settings`` — empty when the pick was invalid or when it
    matched the theme's own background, both of which are stored as "no
    customisation" rather than as a flat colour. Keeping that decision here
    means the AJAX endpoint and the editor UI cannot disagree about whether a
    given pick counts as customised.

    An accent already stored on the profile is preserved: the editor submits
    both colours together, and clearing one must not silently clear the other.
    """
    if profile is None:
        return {}, None, False
    if category is None:
        category = profile_category_slug(profile)
    if theme is None:
        theme = getattr(getattr(profile, 'theme', None), 'name', None)

    submitted = raw if isinstance(raw, dict) else {'background': raw}
    if 'accent' not in submitted:
        existing = profile_theme_settings(profile, category, theme)
        if existing.get('accent'):
            submitted = dict(submitted, accent=existing['accent'])

    settings = normalize_theme_settings(submitted, category, theme)
    colour = normalize_hex_color(submitted.get('background'))
    if not settings:
        profile.theme_settings = {}
        profile.save(update_fields=['theme_settings'])
        return {}, colour, colour is not None

    profile.theme_settings = settings
    profile.save(update_fields=['theme_settings'])
    return settings, colour, False


def apply_accent_selection(profile, raw, category=None, theme=None):
    """Persist a submitted accent pick, keeping any stored background.

    Mirrors :func:`apply_background_selection` for the accent key. Returns
    ``(settings, colour, reset)`` with the same contract, so the editor can
    drive both controls through one code path.
    """
    if profile is None:
        return {}, None, False
    if category is None:
        category = profile_category_slug(profile)
    if theme is None:
        theme = getattr(getattr(profile, 'theme', None), 'name', None)

    submitted = raw if isinstance(raw, dict) else {'accent': raw}
    if 'background' not in submitted:
        existing = profile_theme_settings(profile, category, theme)
        if existing.get('background'):
            submitted = dict(submitted, background=existing['background'])

    settings = normalize_theme_settings(submitted, category, theme)
    colour = normalize_hex_color(submitted.get('accent'))
    if not settings:
        profile.theme_settings = {}
        profile.save(update_fields=['theme_settings'])
        return {}, colour, colour is not None

    profile.theme_settings = settings
    profile.save(update_fields=['theme_settings'])
    return settings, colour, False


def profile_theme_settings(profile, category=None, theme=None):
    """Sanitized copy of ``Profile.theme_settings`` for a profile (or ``None``)."""
    if profile is None:
        return {}
    if category is None:
        category = profile_category_slug(profile)
    if theme is None:
        theme = getattr(getattr(profile, 'theme', None), 'name', None)
    return normalize_theme_settings(
        getattr(profile, 'theme_settings', None) or {}, category, theme
    )


def derive_palette(background):
    """Derive the full token set a supported theme needs from a background.

    Returns a dict of CSS-ready values.

    ``ink`` is always dark because every theme's accent gradient is fixed and
    light, and several rules reuse a background-family token as a foreground on
    top of it. ``hard_ink`` instead flips with the background: it is the
    near-black the neo-brutalist themes draw 3px borders and offset shadows
    with, which has to stay visible on either polarity.

    ``hero_veil`` and ``shadow`` exist for the glass family (Animated, Animated
    Dark, Creative, Creative White), which writes its chrome — navbar bar, hero
    vignette, creator chips, outlined hero type, reels-player chips, avatar ring
    — as literals tuned to one polarity instead of as tokens. Without these the
    recolour would leave a cream navbar and invisible outline text floating on
    a dark page, or a forest of near-white glass chips on a light one. ``grid``
    is the same problem in the hero's hairline overlay.

    ``texture``, ``hairline``, ``star_empty``, ``fill_ink`` and friends serve
    the neo-brutalist family for the same reason. Those themes print a dot-grid
    background, draw hairline rules and floating outlines with it, and invert a
    card on hover by sliding a full-strength fill under the card's own text.
    All three are stated as black-alpha or white-alpha literals tuned to one
    polarity, so a recolour either erases the texture or leaves the hover state
    as white type on a white fill. These tokens carry the polarity with them.

    ``surface_deep`` and ``sheen`` exist for the surface family, and Pro in
    particular. Pro separates its contact, creators and reviews sections by
    painting them a shade *darker* than the body, and lifts its cards with a 3%
    white wash on hover — two ideas no token above can express, because both are
    stated as bare literals (``#050505``, ``#000``, ``rgba(255,255,255,.03)``).
    Left alone they are the two failures that make a recolour look broken on
    Pro specifically: a black band under a white page, and no section edges.

    Deliberately *not* derived here: the theme's accent. Accent colours are the
    brand and do not move when the background does — the stylesheet bridges
    them only where the theme genuinely needs it (see FAMILY_BRUTAL).
    """
    bg = parse_hex_color(background) or parse_hex_color(DEFAULT_BACKGROUND)
    dark = is_dark(bg)

    if dark:
        text = WHITE
        surface = mix(bg, WHITE, 0.10)
        surface_2 = mix(bg, WHITE, 0.18)
        text_muted = mix(WHITE, bg, 0.38)
        text_faint = mix(WHITE, bg, 0.58)
        border = rgba(WHITE, 0.12)
        border_strong = rgba(WHITE, 0.22)
        ink = mix(bg, BLACK, 0.20)
        hard_ink = mix(bg, WHITE, 0.92)
        hero_mid = to_hex(WHITE)
        # A band that sits *below* the page. Pro separates its contact, creators
        # and reviews sections by going darker than the body, so the derived
        # stack has to keep a shade that recedes rather than only shades that
        # lift — otherwise a recoloured page loses every section edge and reads
        # as one undifferentiated block.
        surface_deep = to_hex(mix(bg, BLACK, 0.40))
        # The neo-brutalist dot grid and the hairline rules drawn with it. Both
        # are pure-black on the shipped light themes, so they have to flip to
        # white ink on a dark pick or the texture simply vanishes and the page
        # reads as a flat block.
        texture = rgba(WHITE, 0.10)
        hairline = rgba(WHITE, 0.12)
        star_empty = rgba(WHITE, 0.12)
        # The brutal themes invert on hover by sliding a ``--text`` fill over the
        # card, so everything that then sits *on that fill* has to be the
        # opposite polarity: on a light page a near-black fill carries white
        # type, and on a dark page a near-white fill carries near-black type.
        # Left as white literals, that hover state is white-on-white and the
        # review card loses its body copy entirely.
        fill_ink = rgba(BLACK, 0.85)
        fill_ink_soft = rgba(BLACK, 0.75)
        fill_wash = rgba(BLACK, 0.10)
        fill_empty = rgba(BLACK, 0.25)
        # A black drop shadow under black type is invisible on a dark pick.
        text_shadow = rgba(BLACK, 0.45)
        # The near-invisible sheen a card picks up on hover. White on a dark
        # card, ink on a light one; a white sheen over a light card is simply
        # not there.
        sheen = rgba(WHITE, 0.03)
        # The glass family dims the hero with a dark vignette and drops soft
        # black shadows. On a light pick both are counterproductive — a dark
        # ellipse over light type, and a black smear under light cards — so
        # the veil goes away entirely and the shadow becomes a soft neutral.
        hero_veil = rgba(BLACK, 0.55)
        shadow = rgba(BLACK, 0.5)
        grid = rgba(WHITE, 0.025)
    else:
        text = ACCENT_INK
        surface = mix(bg, BLACK, 0.05)
        surface_2 = mix(bg, BLACK, 0.10)
        text_muted = mix(ACCENT_INK, bg, 0.40)
        text_faint = mix(ACCENT_INK, bg, 0.62)
        border = rgba(ACCENT_INK, 0.14)
        border_strong = rgba(ACCENT_INK, 0.26)
        ink = mix(bg, BLACK, 0.72)
        hard_ink = mix(bg, BLACK, 0.92)
        hero_mid = to_hex(ink)
        hero_veil = 'transparent'
        shadow = rgba((15, 23, 42), 0.12)
        # A light page still needs its section bands to read as bands, so the
        # recessed shade comes from ink rather than from black.
        surface_deep = to_hex(mix(bg, BLACK, 0.06))
        sheen = rgba(BLACK, 0.03)
        # The hero grid is drawn as a 2.5% white hairline overlay. That is
        # deliberately almost invisible, which means it disappears entirely on a
        # light pick and the hero loses the texture it is built around, so the
        # light case gets an ink hairline at a comparable weight.
        grid = rgba(ACCENT_INK, 0.055)
        # Black ink for the neo-brutalist dot grid, the hairline rules drawn
        # with it, and everything that sits on a ``--text`` fill after an
        # inverted hover. These are the shipped weights, so a light recolour
        # keeps the theme's texture exactly as drawn.
        texture = rgba(BLACK, 0.15)
        hairline = rgba(BLACK, 0.08)
        star_empty = rgba(BLACK, 0.12)
        fill_ink = rgba(WHITE, 0.85)
        fill_ink_soft = rgba(WHITE, 0.75)
        fill_wash = rgba(WHITE, 0.10)
        fill_empty = rgba(WHITE, 0.25)
        text_shadow = rgba(BLACK, 0.10)

    return {
        'background': to_hex(bg),
        'dark': dark,
        'ink': to_hex(ink),
        'ink_soft': rgba(ink, 0.80),
        'hard_ink': to_hex(hard_ink),
        'surface': to_hex(surface),
        'surface_2': to_hex(surface_2),
        'surface_deep': surface_deep,
        'surface_glass': rgba(surface_2, 0.90),
        'sheen': sheen,
        'text': to_hex(text),
        'text_muted': to_hex(text_muted),
        'text_faint': to_hex(text_faint),
        'border': border,
        'border_strong': border_strong,
        'nav': rgba(bg, 0.95),
        'overlay': rgba(bg, 0.70),
        'hero_mid': hero_mid,
        'hero_veil': hero_veil,
        'grid': grid,
        'shadow': shadow,
        'texture': texture,
        'hairline': hairline,
        'star_empty': star_empty,
        'fill_ink': fill_ink,
        'fill_ink_soft': fill_ink_soft,
        'fill_wash': fill_wash,
        'fill_empty': fill_empty,
        'text_shadow': text_shadow,
        # Body-text readability, for the editor's live readout. Accents are
        # not included: they are large display type and answer to AA Large.
        'contrast': round(contrast_ratio(bg, text), 1),
    }



def _trio_tone(readable):
    """The third hue of the accent's set — the hue rotated by TRIO_HUE_SHIFT.

    Themes use a third colour decoratively and quite prominently (Creative's
    ambient orbs, its "long form" badge), so leaving the shipped one in place
    after a recolour strands a foreign hue next to the new brand colour. Rotating
    instead of hardcoding keeps the trio a set. Lightness is carried over
    unchanged so the tone holds the same contrast against the background the
    accent itself was just nudged to clear.
    """
    h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in readable))
    if s < 0.08 or l < 0.06:
        return parse_hex_color(TRIO_FALLBACK)
    rotated = colorsys.hls_to_rgb(
        (h + TRIO_HUE_SHIFT) % 1.0, l, min(1.0, max(0.5, s))
    )
    return tuple(int(round(c * 255)) for c in rotated)


def derive_accent_palette(accent, background, adjust=True):
    """Derive the token set an accent needs, given the background it sits on.

    Returns a dict of CSS-ready values. The accent does real work in two
    places, and the derivation has to satisfy both:

    - as *type* on the background (headings, stat figures, section labels) it
      has to clear :data:`ACCENT_MIN_CONTRAST`. A pick that cannot — a navy
      accent on a black page, say — is nudged toward whichever end of the
      lightness range separates it from the background, in small steps, until
      it does. Silently shipping an unreadable accent would be worse than
      shipping a slightly adjusted one, and the editor shows the final value
      so the user sees exactly what they are getting.
    - as a *fill* under small label text (buttons, pills) it carries ``ink``,
      the text colour that sits on top of it, held to full WCAG AA.

    ``partner`` is the second stop of a two-tone gradient and ``glow`` the
    brighter "lit" tone; both lean away from the background so they stay
    distinguishable from it. ``soft`` is a low-alpha wash for tinted fills and
    never has to clear any threshold.

    ``adjust`` exists because the safety net must not fire on a page the user
    never touched. Several themes use a low-contrast accent decoratively — the
    Animated theme's cyan is a gradient stop on a near-white page, not body
    type — so adjusting the shipped pairing would repaint themes that are
    working as designed. Callers therefore pass ``adjust=False`` whenever both
    the accent and the background are the theme's own values, and ``True`` as
    soon as either has been customised.
    """
    base = parse_hex_color(accent) or parse_hex_color(DEFAULT_BACKGROUND)
    bg = parse_hex_color(background) or parse_hex_color(DEFAULT_BACKGROUND)
    dark_bg = is_dark(bg)

    # Push the accent away from the background until it is readable as type.
    readable = base
    if adjust and contrast_ratio(readable, bg) < ACCENT_MIN_CONTRAST:
        away = WHITE if dark_bg else BLACK
        for step in range(1, 21):
            candidate = mix(readable, away, step * 0.05)
            if contrast_ratio(candidate, bg) >= ACCENT_MIN_CONTRAST:
                readable = candidate
                break
        else:
            # Nothing in the ramp cleared the bar; fall back to the end that
            # maximises separation, which always beats the raw pick.
            readable = WHITE if dark_bg else BLACK

    # Round before deriving anything else, so every tone and every reported
    # ratio describes the colour that will actually be written to the page.
    accent_hex = to_hex(readable)
    readable = parse_hex_color(accent_hex)

    # A partner stop reads best slightly off the primary, in the direction that
    # stays visible: lighter on a dark page, deeper on a light one.
    partner_way = WHITE if dark_bg else BLACK
    partner = mix(readable, partner_way, 0.28)
    glow = mix(readable, WHITE, 0.30)
    soft = rgba(readable, 0.14 if dark_bg else 0.12)

    # Text on top of a filled accent: white on a dark accent, near-black on a
    # light one. Button labels are small, so this pair is held to full AA.
    ink = WHITE if is_dark(readable) else BLACK

    # One entry per slot, so the stylesheet partial can address every tone by
    # slot name without special-casing "primary" -> "accent".
    tones = {
        SLOT_PRIMARY: accent_hex,
        SLOT_PARTNER: to_hex(partner),
        SLOT_TRIO: to_hex(_trio_tone(readable)),
        SLOT_GLOW: to_hex(glow),
        SLOT_SOFT: soft,
        SLOT_INK: to_hex(ink),
    }
    palette = {
        # ``accent`` is the historical key for the primary tone; keep it as the
        # alias every template and the editor already read.
        'accent': accent_hex,
        'adjusted': accent_hex != to_hex(base),
        'dark': is_dark(readable),
        # Accent-on-background readability, for the editor's live readout.
        'contrast': round(contrast_ratio(bg, readable), 1),
        'ink_contrast': round(contrast_ratio(readable, ink), 1),
    }
    palette.update(tones)
    # A ``<slot>_rgb`` companion for every tone, so a theme that fades its own
    # accent with rgba() can still follow the colour. See accent_channels.
    for slot, value in tones.items():
        if slot == SLOT_SOFT:
            # ``soft`` is already an rgba() string; its channels are the
            # underlying colour, not the faded one.
            value = to_hex(readable)
        palette['{}_rgb'.format(slot)] = to_rgb_channels(value)
    return palette


def resolve_background_palette(profile, category=None, theme=None):
    """Resolve what a portfolio template needs to paint custom colours.

    Returns ``{'custom': bool, 'accent_custom': bool, 'family': str,
    'background': '#RRGGBB', 'accent': '#RRGGBB', 'accent_tokens': {...},
    'palette': {...}, 'accent_palette': {...}}``.

    ``custom`` is False for themes that do not support the override, and for
    profiles that never saved a background — templates then emit no background
    CSS at all and the theme renders exactly as shipped. ``accent_custom`` is
    the same idea for the accent, tracked separately so a user who only
    recolours their brand colour still gets an override block.
    """
    if category is None:
        category = profile_category_slug(profile)
    if theme is None:
        theme = getattr(getattr(profile, 'theme', None), 'name', None)
    spec = theme_background_spec(category, theme)
    fallback = spec['default'] if spec else DEFAULT_BACKGROUND
    accent_fallback = spec['accent'] if spec else DEFAULT_BACKGROUND
    settings = profile_theme_settings(profile, category, theme)
    background = settings.get('background')
    accent = settings.get('accent')
    # The legibility net only runs once the page has left its shipped state,
    # so an untouched theme still renders exactly as designed.
    customised = bool(background or accent)
    accent_palette = derive_accent_palette(
        accent or accent_fallback, background or fallback, adjust=customised,
    )
    return {
        'custom': bool(background),
        'accent_custom': bool(accent),
        'supported': bool(spec),
        'family': spec['family'] if spec else FAMILY_SURFACE,
        'background': background or fallback,
        'accent': accent or accent_fallback,
        'accent_tokens': accent_tokens(category, theme),
        'accent_channels': accent_channels(category, theme),
        'accent_channel_vars': accent_channel_vars(
            category, theme, accent_palette
        ),
        'palette': derive_palette(background or fallback),
        'accent_palette': accent_palette,
    }


def background_state(profile):
    """Everything the customize pages need to describe a profile's colours.

    ``supported`` gates the whole feature; ``current`` is the saved colour
    (falling back to *this theme's* default) so the editor can pre-select it
    and Reset has something meaningful to return to. The accent keys mirror
    that shape one-for-one.
    """
    category = profile_category_slug(profile)
    theme_name = getattr(getattr(profile, 'theme', None), 'name', '') or ''
    spec = theme_background_spec(category, theme_name)
    default = spec['default'] if spec else DEFAULT_BACKGROUND
    accent_default = spec['accent'] if spec else DEFAULT_BACKGROUND
    settings = profile_theme_settings(profile)
    current = settings.get('background') or default
    accent_current = settings.get('accent') or accent_default
    tokens = accent_tokens(category, theme_name)
    accent_palette = derive_accent_palette(
        accent_current, current, adjust=bool(settings),
    )
    return {
        'supported': bool(spec),
        'custom': bool(settings.get('background')),
        'current': current,
        'default': default,
        'palette': derive_palette(current),
        'family': spec['family'] if spec else FAMILY_SURFACE,
        # The accent in force, adjusted for legibility on ``current`` so the
        # editor's preview wears the colour the page will actually render —
        # but only once the user has customised something, for the reason
        # :func:`derive_accent_palette` documents.
        'accent': accent_current,
        'accent_supported': bool(tokens),
        'accent_custom': bool(settings.get('accent')),
        'accent_default': accent_default,
        'accent_palette': accent_palette,
        'accent_tokens': tokens,
        'accent_channels': accent_channels(category, theme_name),
        'accent_channel_vars': accent_channel_vars(
            category, theme_name, accent_palette
        ),
        'accent_presets': accent_presets_for(category, theme_name) if tokens else [],
        'gradient': (spec or {}).get('gradient') or ('#00D9FF', '#FFFFFF', '#FF006E'),
        'presets': presets_for(category, theme_name) if spec else [],
        # Which flavour of live preview the editor should draw. The generic
        # preview is a video-editor mock-up ("Watch reel", a hero that fills the
        # page with the accent); Developer Classic is a résumé-style page with a
        # compact card grid and a single-column hero, so showing the reel copy
        # there would misdescribe the page the user is about to publish.
        'preview_variant': 'developer' if category == DEVELOPER_CATEGORY else 'editor',
        # Registry-derived, so the "available on X" copy is always exactly as
        # capable as the gate. ``supported_count`` is for the short form (a card
        # cannot carry fourteen theme names); ``supported_categories`` is the
        # long form the locked panel lists.
        'supported_categories': supported_categories(),
        'supported_summary': supported_theme_summary(),
        'supported_count': len(THEME_BACKGROUND_SPECS),
        'theme_name': theme_name,
        'category': category,
    }
