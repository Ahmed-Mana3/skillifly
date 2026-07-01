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
)


# ------------------------------------------------------------------
# Examples Gallery
# ------------------------------------------------------------------

def examples_view(request):
    """Render the live examples page featuring showcased portfolios"""
    showcases = Showcase.objects.filter(is_active=True).select_related('profile__user', 'profile__theme')
    portfolios_count = Profile.objects.count()
    return render(request, 'core/examples.html', {
        'showcases': showcases,
        'portfolios_count': portfolios_count
    })


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
    if not has_active_subscription and profile.is_public:
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    profile.visits += 1
    profile.save(update_fields=['visits'])

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
    uncategorized_count = sum(1 for p in projects_list if p.category_id is None)
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
    }

    # Dynamic template selection based on theme
    template_name = 'portfolios/developer/developer_minimal.html'  # Default fallback
    profile = getattr(user, 'profile', None)

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

    return render(request, template_name, context=context)


# ------------------------------------------------------------------
# Portfolio Video Sub-pages
# ------------------------------------------------------------------

def portfolio_reels(request, username):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    # Visibility Check
    profile = getattr(user, 'profile', None)
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public:
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if profile and not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

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
        template = f"portfolios/{category}/{category}_reels.html"

    context = {
        'projects': projects,
        'type': 'Reels',
        'profile_user': user,
        'username': username,
        'personal_info': personal_info,
        'links': links,
        'category_id': category_id,
    }
    return render(request, template, context)


def portfolio_long_videos(request, username):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    # Visibility Check
    profile = getattr(user, 'profile', None)
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public:
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if profile and not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

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
        template = f"portfolios/{category}/{category}_long.html"

    context = {
        'projects': projects,
        'type': 'Long Videos',
        'profile_user': user,
        'username': username,
        'personal_info': personal_info,
        'links': links,
        'category_id': category_id,
    }
    return render(request, template, context)


def portfolio_video_detail(request, username, slug):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    # Visibility Check
    profile = getattr(user, 'profile', None)
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public:
        profile.is_public = False
        profile.save(update_fields=['is_public'])

    if profile and not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    project = get_object_or_404(Project, user=user, slug=slug)
    personal_info = PersonalInfo.objects.filter(user=user).first()

    category_id = request.GET.get('category_id')
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
        template = f"portfolios/{category}/{category}_detail.html"

    context = {
        'project': project,
        'profile_user': user,
        'personal_info': personal_info,
        'other_videos': other_videos,
        'username': username,
        'category_id': category_id,
    }
    return render(request, template, context)


def portfolio_category_detail(request, username, category_id):
    user = get_object_or_404(CustomUser, username=username)
    profile = getattr(user, 'profile', None)

    if int(category_id) == 0:
        # Mock a category object
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
        if profile:
            profile.visits += 1
            profile.save(update_fields=['visits'])
        request.session[cat_key] = True

    category_slug = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"

    template = f"portfolios/{category_slug}/{category_slug}_{theme_name}_category.html"
    from django.template.exceptions import TemplateDoesNotExist
    from django.template.loader import get_template
    try:
        get_template(template)
    except TemplateDoesNotExist:
        template = f"portfolios/{category_slug}/{category_slug}_category.html"

    personal_info = PersonalInfo.objects.filter(user=user).first()
    
    context = {
        'portfolio_user': user,
        'profile': profile,
        'category': category,
        'projects': projects,
        'personal_info': personal_info,
        'username': username,
    }
    return render(request, template, context)
