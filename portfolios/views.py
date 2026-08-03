"""
portfolios/views.py

Public-facing portfolio rendering views, extracted from core.views.
All models are imported from core.models (zero-migration strategy).
"""

from django.shortcuts import render, get_object_or_404
from django.db.models import Count
from django.template import TemplateDoesNotExist
from django.template.loader import get_template

from core.models import (
    CustomUser,
    Profile,
    PersonalInfo,
    Experience,
    Education,
    Skill,
    Project,
    Link,
    Creator,
    ProjectCategory,
    UserPayment,
    Showcase,
    Theme,
)


# ------------------------------------------------------------------
# Examples Gallery
# ------------------------------------------------------------------


def get_or_create_mock_user():
    from datetime import date
    user, created = CustomUser.objects.get_or_create(
        username='alex_mercer',
        defaults={
            'first_name': 'Alex',
            'last_name': 'Mercer',
            'email': 'alex@example.com',
            'is_active': False,
        }
    )
    if created:
        Profile.objects.create(user=user, is_public=True, visits=0)
        PersonalInfo.objects.create(
            user=user,
            full_name="Alex Mercer",
            title="Creative Video Editor & Motion Designer",
            email="alex@example.com",
            phone="+1 234 567 8900",
            bio="I'm a passionate video editor with 5+ years of experience crafting compelling visual stories for brands and creators. I specialize in dynamic pacing, motion graphics, and color grading to bring ideas to life.",
            booking_url="https://calendly.com"
        )
        Link.objects.create(user=user, platform="Instagram", url="https://instagram.com")
        Link.objects.create(user=user, platform="LinkedIn", url="https://linkedin.com")
        Link.objects.create(user=user, platform="Twitter", url="https://twitter.com")

        Experience.objects.create(user=user, title="Senior Video Editor", company="Creative Studio", start_date=date(2021, 1, 1), still_working=True, duration=3.5, details="Led post-production for major ad campaigns, reducing turnaround time by 20%.")
        Experience.objects.create(user=user, title="Motion Designer", company="Freelance", start_date=date(2018, 5, 1), end_date=date(2020, 12, 31), duration=2.5, details="Created engaging motion graphics for various YouTube channels and social media pages.")

        Education.objects.create(user=user, school="Film Institute", degree="B.A. Film Production", field="Editing", grade_year=date(2018, 1, 1))

        Skill.objects.create(user=user, name="Premiere Pro")
        Skill.objects.create(user=user, name="After Effects")
        Skill.objects.create(user=user, name="DaVinci Resolve")
        Skill.objects.create(user=user, name="Color Grading")

        cat1 = ProjectCategory.objects.create(user=user, name="Commercials", description="High-end commercials for brands")
        cat2 = ProjectCategory.objects.create(user=user, name="Social Media", description="Fast-paced social media content")

        Project.objects.create(user=user, title="Nike - Urban Run", video_type="long", category=cat1, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", slug="nike-urban-run", image="projects/preview_thumbnail.png", details="A fast-paced energetic commercial showcasing high-intensity urban running and brand aesthetic.")
        Project.objects.create(user=user, title="Tech Startup Promo", video_type="long", category=cat1, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", slug="tech-startup-promo", image="projects/preview_thumbnail.png", details="Sleek motion graphics and clean cuts introducing a revolutionary SaaS platform.")
        Project.objects.create(user=user, title="Fitness Reel", video_type="reel", category=cat2, url="https://drive.google.com/file/d/1L65bwWPYhSfLHWCMWF9LM_Truoa1qtm9/preview", slug="fitness-reel", image="projects/preview_thumbnail.png", details="Dynamic vertical short-form reel designed for high retention and engagement.")
        Project.objects.create(user=user, title="Travel Vlog Teaser", video_type="reel", category=cat2, url="https://drive.google.com/file/d/1L65bwWPYhSfLHWCMWF9LM_Truoa1qtm9/preview", slug="travel-vlog-teaser", image="projects/preview_thumbnail.png", details="Cinematic color-graded teaser featuring breathtaking drone shots and sound design.")

        Creator.objects.create(user=user, name="MrBeast", url="https://youtube.com/@mrbeast", image="creators/creator_mrbeast.png")
        Creator.objects.create(user=user, name="Ali Abdaal", url="https://youtube.com/@aliabdaal", image="creators/creator_aliabdaal.png")
        Creator.objects.create(user=user, name="MKBHD", url="https://youtube.com/@mkbhd", image="creators/creator_mkbhd.png")
        Creator.objects.create(user=user, name="Peter McKinnon", url="https://youtube.com/@petermckinnon", image="creators/creator_petermckinnon.png")

    return user


def examples_view(request):
    """Render the live examples page featuring showcased portfolios"""
    showcases = Showcase.objects.filter(is_active=True).select_related('profile__user', 'profile__theme')
    portfolios_count = Profile.objects.count()
    return render(request, 'core/examples.html', {
        'showcases': showcases,
        'portfolios_count': portfolios_count
    })


def arabic_examples_view(request):
    """Render the Arabic examples page variant for the language toggle."""
    showcases = Showcase.objects.filter(is_active=True).select_related('profile__user', 'profile__theme')
    portfolios_count = Profile.objects.count()
    return render(request, 'core/arabic_examples.html', {
        'showcases': showcases,
        'portfolios_count': portfolios_count,
        'is_arabic_page': True,
    })


# ------------------------------------------------------------------
# Direct Theme Preview URL (skillifly.cloud/preview/theme_name)
# ------------------------------------------------------------------

def theme_preview_view(request, theme_name):
    """
    Render portfolio theme preview using consistent mock data.
    URL format: /preview/<theme_name>
    """
    normalized = theme_name.lower().replace("-", "_").replace(" ", "_")

    # Match theme from database
    theme = None
    all_themes = Theme.objects.select_related('category').all()
    for t in all_themes:
        t_slug = t.name.lower().replace("-", "_").replace(" ", "_")
        if t_slug == normalized or str(t.id) == theme_name:
            theme = t
            break

    if not theme:
        for t in all_themes:
            if normalized in t.name.lower().replace("-", "_").replace(" ", "_"):
                theme = t
                break

    if getattr(theme, 'id', 0) > 0:
        request.session['preview_theme'] = theme.id
        
    get_or_create_mock_user()
    
    return preview_view(request, 'alex_mercer')


def _inject_preview_bar(request, response, profile, user):
    """Helper to inject the preview bar HTML into the response for theme previews."""
    if user.username != 'alex_mercer':
        return response

    preview_theme_id = request.GET.get('preview_theme') or request.session.get('preview_theme')
    
    if preview_theme_id and hasattr(profile, 'theme') and profile.theme:
        from django.middleware.csrf import get_token
        csrf_token = get_token(request)
        theme_name = profile.theme.name
        
        bar_html = f"""
        <style>
            .preview-bar-container {{
                position: fixed; bottom: 0; left: 0; right: 0; background: #0f172a; color: white; padding: 16px 24px; z-index: 999999; display: flex; justify-content: space-between; align-items: center; font-family: 'Inter', system-ui, sans-serif; box-shadow: 0 -10px 25px -5px rgba(0, 0, 0, 0.3);
            }}
            .preview-bar-left {{
                display: flex; align-items: center; gap: 16px;
            }}
            .preview-bar-right {{
                display: flex; gap: 12px; align-items: center;
            }}
            .preview-btn-back {{
                background: transparent; border: 1px solid #475569; color: white; padding: 10px 20px; border-radius: 99px; cursor: pointer; font-weight: 600; font-size: 14px; text-decoration: none; transition: all 0.2s; text-align: center; display: inline-block;
            }}
            .preview-btn-back:hover {{ background: #1e293b; }}
            .preview-btn-apply {{
                background: #3b82f6; border: none; color: white; padding: 10px 24px; border-radius: 99px; cursor: pointer; font-weight: 600; font-size: 14px; box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.5); transition: all 0.2s; width: 100%;
            }}
            .preview-btn-apply:hover {{ transform: scale(1.05); }}
            
            @media (max-width: 640px) {{
                .preview-bar-container {{
                    flex-direction: column; padding: 12px 16px; gap: 12px;
                }}
                .preview-bar-left {{ width: 100%; justify-content: flex-start; }}
                .preview-bar-right {{ width: 100%; justify-content: center; }}
                .preview-bar-right form {{ flex: 1; }}
                .preview-btn-back {{ flex: 1; padding: 10px 12px; font-size: 13px; }}
                .preview-btn-apply {{ padding: 10px 12px; font-size: 13px; }}
            }}
        </style>
        <div class="preview-bar-container">
            <div class="preview-bar-left">
                <div style="width: 40px; height: 40px; background: linear-gradient(135deg, #3b82f6, #8b5cf6); border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <svg style="width: 20px; height: 20px; color: white;" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                </div>
                <div>
                    <p style="margin: 0; font-size: 12px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Preview Mode</p>
                    <p style="margin: 0; font-size: 16px; font-weight: 700;">{theme_name} Theme</p>
                </div>
            </div>
            <div class="preview-bar-right">
                <a href="/themes/" class="preview-btn-back">Back to Themes</a>
                <form method="POST" action="/themes/" style="margin: 0; display: flex; flex: 1;">
                    <input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">
                    <input type="hidden" name="theme" value="{profile.theme.id}">
                    <button type="submit" class="preview-btn-apply">Apply Theme</button>
                </form>
            </div>
        </div>
        """
        
        content = response.content.decode('utf-8')
        if '</body>' in content:
            content = content.replace('</body>', bar_html + '</body>')
        else:
            content += bar_html
            
        response.content = content.encode('utf-8')
        
    return response


# ------------------------------------------------------------------
# Main Portfolio Preview
# ------------------------------------------------------------------

def preview_view(request, username):
    # Handle optional @ prefix from sitemap or direct links
    clean_username = username.lstrip('@')

    user = get_object_or_404(CustomUser, username=clean_username)

    # Increment visit counter (update only the visits field to avoid a full model save)
    profile, created = Profile.objects.get_or_create(user=user)

    # Visibility Check
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    # Auto-flip to private if not subscribed
    if not has_active_subscription and profile.is_public and user.username != 'alex_mercer':
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if not profile.is_public and request.user != user and user.username != 'alex_mercer':
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    # Don't log visits for mock user
    if user.username != 'alex_mercer':
        profile.visits += 1
        profile.save(update_fields=['visits'])

    preview_theme_id = request.GET.get('preview_theme')
    if preview_theme_id:
        request.session['preview_theme'] = preview_theme_id
    elif user.username == 'alex_mercer':
        preview_theme_id = request.session.get('preview_theme')
    else:
        preview_theme_id = None

    personal_info = PersonalInfo.objects.filter(user=user).select_related('user').first()
    experiences = Experience.objects.filter(user=user).select_related('user')
    education = Education.objects.filter(user=user).select_related('user')
    skills = Skill.objects.filter(user=user).select_related('user')
    projects = Project.objects.filter(user=user).select_related('user', 'category')
    links = Link.objects.filter(user=user).select_related('user')
    creators = Creator.objects.filter(user=user).select_related('user')

    # Prefetch categories with annotated project counts in a SINGLE query — eliminates N+1
    project_categories = list(
        ProjectCategory.objects.filter(user=user)
        .annotate(project_count=Count('projects'))
        .order_by('id')
    )

    # Cinematic/video-editor themes need safe numeric highlights
    # Use cached querysets to avoid re-hitting the DB
    projects_list = list(projects)
    project_count = len(projects_list)
    long_count = sum(1 for p in projects_list if p.video_type == 'long')
    reel_count = sum(1 for p in projects_list if p.video_type == 'reel')
    uncategorized_count = sum(1 for p in projects_list if getattr(p, 'category_id', None) is None)
    has_uncategorized_projects = uncategorized_count > 0

    context = {
        'personal_info': personal_info,
        'experiences': experiences,
        'education': education,
        'skills': skills,
        'projects': projects,
        'links': links,
        'creators': creators,
        'username': clean_username,
        'project_count': project_count,
        'long_count': long_count,
        'reel_count': reel_count,
        'portfolio_user': user,
        'profile': profile,
        'uncategorized_count': uncategorized_count,
        'has_uncategorized_projects': has_uncategorized_projects,
        # Pre-evaluated list with annotated counts — no extra DB queries in templates
        'project_categories': project_categories,
        'project_categories_count': len(project_categories),
        'is_noindex': False,
    }

    # Dynamic template selection based on theme
    template_name = 'portfolios/developer/developer_minimal.html'  # Default fallback

    # Handle theme preview for demo portfolio only
    if preview_theme_id and user.username == 'alex_mercer':
        try:
            preview_theme = Theme.objects.get(id=preview_theme_id)
            if profile:
                profile.theme = preview_theme
            else:
                class MockProfile:
                    theme = preview_theme
                    is_public = True
                    visits = 0
                profile = MockProfile()
                context['profile'] = profile
        except Theme.DoesNotExist:
            pass

    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        # Template folder structure: portfolios/category/category_theme.html
        specific_template = f"portfolios/{category}/{category}_{theme_name}.html"

        try:
            # Check if template exists
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            template_name = 'portfolios/developer/developer_minimal.html'

    response = render(request, template_name, context=context)
    return _inject_preview_bar(request, response, profile, user)


# ------------------------------------------------------------------
# Portfolio Video Sub-pages
# ------------------------------------------------------------------

def portfolio_reels(request, username):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    profile = getattr(user, 'profile', None)
    
    preview_theme_id = request.GET.get('preview_theme') or request.session.get('preview_theme')
    can_preview = (user.username == 'alex_mercer') or (request.user.is_authenticated and request.user == user)
    
    if preview_theme_id and can_preview:
        try:
            preview_theme = Theme.objects.get(id=preview_theme_id)
            if profile:
                profile.theme = preview_theme
            else:
                class MockProfile:
                    theme = preview_theme
                profile = MockProfile()
        except Theme.DoesNotExist:
            pass

    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public and user.username != 'alex_mercer':
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if profile and not profile.is_public and request.user != user and user.username != 'alex_mercer':
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    if user.username != 'alex_mercer' and profile:
        profile.visits += 1
        profile.save(update_fields=['visits'])

    category_id = request.GET.get('category_id')
    if category_id:
        if category_id == '0':
            projects = Project.objects.filter(user=user, video_type='reel', category__isnull=True)
        else:
            projects = Project.objects.filter(user=user, video_type='reel', category_id=category_id)
    else:
        projects = Project.objects.filter(user=user, video_type='reel')

    personal_info = PersonalInfo.objects.filter(user=user).first()
    links = Link.objects.filter(user=user)

    # Dynamic template selection
    category = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"

    template = f"portfolios/{category}/{category}_{theme_name}_reels.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        try:
            template = f"portfolios/{category}/{category}_reels.html"
            get_template(template)
        except TemplateDoesNotExist:
            template = "portfolios/video_editor/video_editor_reels.html"

    context = {
        'projects': projects,
        'type': 'Reels',
        'profile_user': user,
        'username': username,
        'personal_info': personal_info,
        'links': links,
        'category_id': category_id,
        'is_noindex': True,
    }
    return render(request, template, context)


def portfolio_long_videos(request, username):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    profile = getattr(user, 'profile', None)
    
    preview_theme_id = request.GET.get('preview_theme') or request.session.get('preview_theme')
    can_preview = (user.username == 'alex_mercer') or (request.user.is_authenticated and request.user == user)
    
    if preview_theme_id and can_preview:
        try:
            preview_theme = Theme.objects.get(id=preview_theme_id)
            if profile:
                profile.theme = preview_theme
            else:
                class MockProfile:
                    theme = preview_theme
                profile = MockProfile()
        except Theme.DoesNotExist:
            pass

    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public and user.username != 'alex_mercer':
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if profile and not profile.is_public and request.user != user and user.username != 'alex_mercer':
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    if user.username != 'alex_mercer' and profile:
        profile.visits += 1
        profile.save(update_fields=['visits'])

    category_id = request.GET.get('category_id')
    if category_id:
        if category_id == '0':
            projects = Project.objects.filter(user=user, video_type='long', category__isnull=True)
        else:
            projects = Project.objects.filter(user=user, video_type='long', category_id=category_id)
    else:
        projects = Project.objects.filter(user=user, video_type='long')

    personal_info = PersonalInfo.objects.filter(user=user).first()
    links = Link.objects.filter(user=user)

    # Dynamic template selection
    category = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"

    template = f"portfolios/{category}/{category}_{theme_name}_long.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        try:
            template = f"portfolios/{category}/{category}_long.html"
            get_template(template)
        except TemplateDoesNotExist:
            template = "portfolios/video_editor/video_editor_long.html"

    context = {
        'projects': projects,
        'type': 'Long Videos',
        'profile_user': user,
        'username': username,
        'personal_info': personal_info,
        'links': links,
        'category_id': category_id,
        'is_noindex': True,
    }
    return render(request, template, context)


def portfolio_video_detail(request, username, slug):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    profile = getattr(user, 'profile', None)
    
    preview_theme_id = request.GET.get('preview_theme') or request.session.get('preview_theme')
    can_preview = (user.username == 'alex_mercer') or (request.user.is_authenticated and request.user == user)
    
    if preview_theme_id and can_preview:
        try:
            preview_theme = Theme.objects.get(id=preview_theme_id)
            if profile:
                profile.theme = preview_theme
            else:
                class MockProfile:
                    theme = preview_theme
                profile = MockProfile()
        except Theme.DoesNotExist:
            pass

    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public and user.username != 'alex_mercer':
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if profile and not profile.is_public and request.user != user and user.username != 'alex_mercer':
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    personal_info = PersonalInfo.objects.filter(user=user).first()
    category_id = request.GET.get('category_id')

    project = get_object_or_404(Project, user=user, slug=slug)
    if category_id:
        if category_id == '0':
            other_videos = Project.objects.filter(user=user, video_type='long', category__isnull=True).exclude(id=project.id)
        else:
            other_videos = Project.objects.filter(user=user, video_type='long', category_id=category_id).exclude(id=project.id)
    else:
        if project.category:
            other_videos = Project.objects.filter(user=user, video_type='long', category=project.category).exclude(id=project.id)
        else:
            other_videos = Project.objects.filter(user=user, video_type='long', category__isnull=True).exclude(id=project.id)

    category = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"

    template = f"portfolios/{category}/{category}_{theme_name}_detail.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        try:
            template = f"portfolios/{category}/{category}_detail.html"
            get_template(template)
        except TemplateDoesNotExist:
            template = "portfolios/video_editor/video_editor_detail.html"

    context = {
        'project': project,
        'profile_user': user,
        'personal_info': personal_info,
        'other_videos': other_videos,
        'username': username,
        'category_id': category_id,
        'is_noindex': True,
    }
    return render(request, template, context)


def portfolio_category_detail(request, username, category_id):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    profile = getattr(user, 'profile', None)

    preview_theme_id = request.GET.get('preview_theme') or request.session.get('preview_theme')
    can_preview = (user.username == 'alex_mercer') or (request.user.is_authenticated and request.user == user)
    
    if preview_theme_id and can_preview:
        try:
            preview_theme = Theme.objects.get(id=preview_theme_id)
            if profile:
                profile.theme = preview_theme
            else:
                class MockProfile:
                    theme = preview_theme
                profile = MockProfile()
        except Theme.DoesNotExist:
            pass

    personal_info = PersonalInfo.objects.filter(user=user).first()

    if int(category_id) == 0:
        class MockCategory:
            id = 0
            name = 'Other Videos'
            description = 'Uncategorized projects and videos.'
        category = MockCategory()
        projects = Project.objects.filter(user=user, category__isnull=True)
    else:
        category = get_object_or_404(ProjectCategory, user=user, id=category_id)
        projects = Project.objects.filter(user=user, category=category)

    # simple view tracking
    cat_key = f'viewed_category_{category.id}'
    if not request.session.get(cat_key, False):
        if profile and hasattr(profile, 'save') and user.username != 'alex_mercer':
            profile.visits += 1
            profile.save(update_fields=['visits'])
        request.session[cat_key] = True

    category_slug = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"

    template = f"portfolios/{category_slug}/{category_slug}_{theme_name}_category.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        try:
            template = f"portfolios/{category_slug}/{category_slug}_category.html"
            get_template(template)
        except TemplateDoesNotExist:
            template = "portfolios/video_editor/video_editor_categories_long.html"

    context = {
        'portfolio_user': user,
        'profile': profile,
        'category': category,
        'projects': projects,
        'personal_info': personal_info,
        'username': username,
        'is_noindex': True,
    }
    return render(request, template, context)
