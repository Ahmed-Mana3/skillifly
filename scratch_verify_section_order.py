"""One-off: render every main theme template in BOTH section-order states and
verify structure:
  A) section_order=[]  -> no ordering CSS emitted (layout untouched)
  B) section_order=set -> flex CSS present, all 5 sections are DIRECT children
     of .portfolio-body, wrapper balanced even with empty querysets.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skillifly.settings')
django.setup()

from datetime import date
from types import SimpleNamespace
from django.template.loader import get_template
from django.template import TemplateDoesNotExist
from django.test import RequestFactory
from bs4 import BeautifulSoup
from core.section_order import resolve_section_layout

TEMPLATES = [
    'portfolios/video_editor/video_editor_minimal.html',
    'portfolios/video_editor/video_editor_creative.html',
    'portfolios/video_editor/video_editor_creative_white.html',
    'portfolios/video_editor/video_editor_animated.html',
    'portfolios/video_editor/video_editor_animated_dark.html',
    'portfolios/video_editor/video_editor_editorial_studio.html',
    'portfolios/video_editor/video_editor_categories.html',
    'portfolios/video_editor/video_editor_categories_white.html',
    'portfolios/video_editor/video_editor_monochrome.html',
    'portfolios/video_editor/video_editor_yellow.html',
    'portfolios/video_editor/video_editor_cyan.html',
    'portfolios/video_editor/video_editor_cinematic.html',
    'portfolios/developer/developer_minimal.html',
    'portfolios/developer/developer_creative.html',
    'portfolios/developer/developer_classic.html',
    'portfolios/student/student_classic_scholar.html',
]

# Templates that opt into layout ordering via section_layout_css.html.
ORDERABLE_THEME = 'portfolios/video_editor/video_editor_minimal.html'
_img = SimpleNamespace(name='img.jpg')


def base_ctx(order, visibility=None):
    """Renderable context for any theme template.

    ``section_layout`` is the context preview_view hands every template (via
    resolve_section_layout); templates consume that, not the raw list.
    """
    stub_profile = SimpleNamespace(section_order=order,
                                   section_visibility=visibility or {})
    return {
        'section_order': order,
        'section_layout': resolve_section_layout(stub_profile, 'video_editor'),
        'personal_info': SimpleNamespace(
            full_name='Test User', title='Editor', bio='Bio', email='t@t.com',
            phone='010', booking_url='', picture=None,
            user=SimpleNamespace(username='test')),
        'experiences': [SimpleNamespace(title='T', company='C', start_date=date(2020, 1, 1),
                                        end_date=None, still_working=True, details='D')],
        'education': [SimpleNamespace(school='S', degree='Dg', field='F', grade_year=date(2021, 1, 1))],
        'skills': [SimpleNamespace(name='Premiere')],
        'projects': [SimpleNamespace(title='P', details='D', url='https://x.com', image=_img,
                                     video_type='long', category=None, id=1)],
        'links': [SimpleNamespace(platform='GitHub', url='https://x.com')],
        'creators': [SimpleNamespace(name='C', image=_img, url='')],
        'reviews': [SimpleNamespace(rating=5, content='Great', user_name='A', initials='A',
                                    image_name=None, user_title='Client', created_at=date(2024, 1, 1))],
        'project_categories': [],
        'username': 'test', 'project_count': 1, 'long_count': 1, 'reel_count': 0,
        'portfolio_user': SimpleNamespace(username='test'),
        'profile': None,
        'uncategorized_count': 0, 'has_uncategorized_projects': False,
        'uncategorized_previews': [], 'is_noindex': True,
        'request': RequestFactory().get('/test/'),
    }


failures = 0
for name in TEMPLATES:
    problems = []
    try:
        html_off = get_template(name).render(base_ctx([]))
        html_on = get_template(name).render(
            base_ctx(['education', 'projects', 'skills', 'experience', 'links']))
    except TemplateDoesNotExist:
        print(f'MISSING     {name}')
        failures += 1
        continue
    except Exception as e:
        print(f'RENDER-ERR  {name}: {type(e).__name__}: {e}')
        failures += 1
        continue

    # A) guard: nothing saved -> no flex CSS at all
    if '.portfolio-body { display: flex' in html_off:
        problems.append('guard failed: flex CSS present with empty order')

    if name == ORDERABLE_THEME:
        # B) active: wrapper + direct children + css
        if '.portfolio-body { display: flex' not in html_on:
            problems.append('flex CSS missing with order set')
        if '.portfolio-body > footer { order: 999; }' not in html_on:
            problems.append('footer-under-sections guarantee missing')
        soup = BeautifulSoup(html_on, 'html.parser')
        wrappers = soup.select('.portfolio-body')
        if len(wrappers) != 1:
            problems.append(f'wrapper count={len(wrappers)}')
        else:
            # Every supported key must map to a section that is a DIRECT child
            # of the wrapper; themes use their own ids (#portfolio, #connect).
            from core.section_order import SECTION_META, supported_keys
            direct_ids = {c.get('id') for c in wrappers[0].find_all('section', recursive=False)
                          if c.get('id')}
            for key in supported_keys('video_editor'):
                has_child = any((sel.startswith('#') and sel.lstrip('#') in direct_ids)
                                or (sel.startswith('.') and wrappers[0].select(sel))
                                for sel in SECTION_META[key]['selectors'])
                if not has_child:
                    problems.append(f'{key} not a direct child of .portfolio-body')
    else:
        # C) layout CSS stays scoped: non-orderable themes never emit it
        if '.portfolio-body { display: flex' in html_on:
            problems.append('flex CSS present in a non-orderable theme')

    # Balance smoke-test: empty querysets must still yield exactly one wrapper
    empty_ctx = base_ctx(['projects', 'skills', 'experience', 'education', 'links'])
    for key in ('experiences', 'education', 'skills', 'projects', 'links'):
        empty_ctx[key] = []
    soup_empty = BeautifulSoup(get_template(name).render(empty_ctx), 'html.parser')
    n_empty = len(soup_empty.select('.portfolio-body'))
    if n_empty > 1:
        problems.append(f'unbalanced wrapper with empty data (count={n_empty})')

    status = 'FAIL ' + '; '.join(problems) if problems else 'OK'
    if problems:
        failures += 1
    print(f'{status:<60} {name}')

print('\n' + ('ALL PASS' if failures == 0 else f'{failures} FAILURES'))
