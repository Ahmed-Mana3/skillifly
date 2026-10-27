from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
import logging

from builder import services
from core import activation, onboarding

logger = logging.getLogger(__name__)

# Import models from core
from core.models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser, UserPayment, Review, ClientReview, Showcase, SEOSettings, ManualPayment, Creator, ProjectCategory

# Import forms from builder
from builder.forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    LinkFormSet,
    CreatorFormSet,
    ProjectCategoryFormSet,
    SkillFormSetUpdate,
    EducationFormSetUpdate,
    ExperienceFormSetUpdate,
    ProjectFormSetUpdate,
    LinkFormSetUpdate,
    CreatorFormSetUpdate,
    ProjectCategoryFormSetUpdate,
    ProjectForm,
)

@login_required
@require_POST
def ajax_save_section_layout(request):
    """AJAX endpoint to save/reset the portfolio section order and visibility."""
    from core.section_order import (
        normalize_section_order,
        normalize_section_visibility,
        profile_theme_slug,
        supported_keys,
    )
    import json

    profile, _ = Profile.objects.get_or_create(user=request.user)
    category = (
        profile.theme.category.name.lower().replace(' ', '_')
        if profile.theme and profile.theme.category
        else 'video_editor'
    )
    # Themes with their own DOM order (categories) validate against their
    # own supported set, not the family default.
    theme = profile_theme_slug(profile)

    # --- Reset ---
    if request.POST.get('reset') == '1':
        profile.section_order = []
        profile.section_visibility = {}
        profile.save(update_fields=['section_order', 'section_visibility'])
        return JsonResponse({'success': True, 'reset': True})

    raw_order = request.POST.get('section_order', '')
    raw_visibility = request.POST.get('section_visibility', '')

    try:
        order_candidates = json.loads(raw_order) if raw_order else []
    except (ValueError, TypeError):
        order_candidates = []

    supported = supported_keys(category, theme)
    allowed = set(supported)

    invalid_order = [k for k in order_candidates if k not in allowed]
    if invalid_order:
        return JsonResponse({'success': False, 'invalid_keys': invalid_order}, status=400)

    order_list = normalize_section_order(order_candidates, category, theme)

    visibility_map = normalize_section_visibility(raw_visibility, category, theme)
    if raw_visibility:
        raw_vis_keys = set()
        try:
            raw_vis_keys = set(json.loads(raw_visibility).keys())
        except (ValueError, TypeError):
            pass
        invalid_vis = [k for k in raw_vis_keys if k not in allowed]
        if invalid_vis:
            return JsonResponse({'success': False, 'invalid_keys': invalid_vis}, status=400)

    # Prevent hiding every section
    visible_count = sum(1 for k in allowed if visibility_map.get(k, True))
    if visible_count == 0:
        return JsonResponse({'success': False, 'error': 'At least one section must be visible.'}, status=400)

    # Keep only real overrides (hidden sections); "visible: true" entries are
    # the model's implied default. A result indistinguishable from the theme
    # default is stored as "no custom layout" so the builder status chip and
    # resolve_section_layout stay truthful after a user drags everything back.
    visibility_map = {k: v for k, v in visibility_map.items() if v is False}
    if order_list == list(supported) and not visibility_map:
        profile.section_order = []
        profile.section_visibility = {}
    else:
        profile.section_order = order_list
        profile.section_visibility = visibility_map
    profile.save(update_fields=['section_order', 'section_visibility'])
    return JsonResponse({'success': True})


@login_required
@require_POST
def ajax_save_section_names(request):
    """AJAX endpoint to save/reset custom portfolio section names."""
    from core.section_order import (
        normalize_section_names,
        profile_theme_slug,
    )

    profile, _ = Profile.objects.get_or_create(user=request.user)
    category = (
        profile.theme.category.name.lower().replace(' ', '_')
        if profile.theme and profile.theme.category
        else 'video_editor'
    )
    theme = profile_theme_slug(profile)

    if request.POST.get('reset') == '1':
        profile.section_names = {}
        profile.save(update_fields=['section_names'])
        return JsonResponse({'success': True, 'reset': True})

    raw_names = request.POST.get('section_names', '')
    names_map = normalize_section_names(raw_names, category, theme)

    profile.section_names = names_map
    profile.save(update_fields=['section_names'])
    return JsonResponse({'success': True})


@login_required
@require_POST
def ajax_save_category(request):
    """AJAX endpoint to instantly save or update a ProjectCategory."""
    from core.models import ProjectCategory
    
    category_id = request.POST.get('id')
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'Category name is required.'}, status=400)
    
    description = request.POST.get('description', '').strip()
    thumbnail = request.FILES.get('thumbnail')
    
    if category_id:
        # Update existing category
        cat = get_object_or_404(ProjectCategory, user=request.user, id=category_id)
        # Prevent renaming to a duplicate name of another category
        if ProjectCategory.objects.filter(user=request.user, name=name).exclude(id=cat.id).exists():
            return JsonResponse({'success': False, 'error': 'A category with this name already exists.'}, status=400)
        cat.name = name
        cat.description = description
        if thumbnail:
            cat.thumbnail = thumbnail
        cat.save()
        created = False
    else:
        # Prevent duplicates for this user
        if ProjectCategory.objects.filter(user=request.user, name=name).exists():
            return JsonResponse({'success': False, 'error': 'A category with this name already exists.'}, status=400)
        cat = ProjectCategory.objects.create(
            user=request.user,
            name=name,
            description=description,
            thumbnail=thumbnail
        )
        created = True
    
    thumb_url = cat.thumbnail.url if cat.thumbnail else None
    
    return JsonResponse({
        'success': True,
        'id': cat.id,
        'name': cat.name,
        'description': cat.description or '',
        'thumbnail_url': thumb_url,
        'created': created,
    })


@login_required
@require_POST
def ajax_delete_category(request):
    """AJAX endpoint to instantly delete a ProjectCategory."""
    from core.models import ProjectCategory
    category_id = request.POST.get('id')
    if not category_id:
        return JsonResponse({'success': False, 'error': 'Category ID is required.'}, status=400)
    
    category = get_object_or_404(ProjectCategory, user=request.user, id=category_id)
    category.delete()
    return JsonResponse({'success': True})


@login_required
def builder_view(request):
    return _builder_flow(request)


@login_required
def arabic_builder_view(request):
    """Arabic (RTL) twin of builder_view served at /ar/builder/."""
    return _builder_flow(request, arabic=True)


def _page_context(request, arabic):
    """What the builder's header, readiness card, video cards and skill chips need."""
    user = request.user
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    is_live = bool(payment and payment.is_active and Profile.objects.filter(user=user, is_public=True).exists())
    portfolio_path = reverse('preview', kwargs={'username': user.username})
    return {
        "autosave_enabled": services.autosave_enabled(),
        "autosave_api_base": reverse("builder_api_personal").rsplit("personal/", 1)[0],
        "is_live": is_live,
        "preview_url": portfolio_path,
        "portfolio_url": request.build_absolute_uri(portfolio_path),
        "publish_url": reverse('arabic_payment' if arabic else 'payment') + '?ra=live',
        "link_preview_url": reverse('welcome_preview_link'),
        "projects_order_url": reverse('builder_api_projects_order'),
        "skill_presets": services.skill_presets(arabic),
        "title_confirmed": PersonalInfo.objects.filter(user=user, title_confirmed=True).exists(),
    }


def _invalid_sections(**forms):
    """Names of the sections whose form/formset failed validation (for analytics)."""
    return [name for name, form in forms.items() if not form.is_valid()]


def _first_project_redirect(request, had_projects, arabic):
    """Redirect to the user's own portfolio when this save created their first project.

    Returns None otherwise, so the caller keeps its normal redirect.
    """
    if not had_projects and Project.objects.filter(user=request.user).exists():
        return redirect(onboarding.reveal_url(request.user, arabic))
    return None


def _builder_flow(request, arabic=False):
    if request.method == "GET":
        # Editors without a theme would otherwise preview as the developer template.
        onboarding.ensure_default_theme(request.user)

    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST, request.FILES)

        skill_formset = SkillFormSet(request.POST, prefix="skills")
        education_formset = EducationFormSet(request.POST, prefix="education")
        experience_formset = ExperienceFormSet(request.POST, prefix="experience")
        project_formset = ProjectFormSet(request.POST, request.FILES, prefix="projects", form_kwargs={"user": request.user, "arabic": arabic})
        project_category_formset = ProjectCategoryFormSet(request.POST, request.FILES, prefix="project_categories")
        link_formset = LinkFormSet(request.POST, prefix="links")
        creator_formset = CreatorFormSet(request.POST, request.FILES, prefix="creators")

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
            and creator_formset.is_valid()
        ):

            had_projects = Project.objects.filter(user=request.user).exists()
            with activation.source('builder'):
                save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset, arabic=arabic)
            activation.track(
                request.user, 'builder_saved', flow='builder',
                projects=Project.objects.filter(user=request.user).count(),
            )

            services.publish_if_paid(request.user)

            first_project = _first_project_redirect(request, had_projects, arabic)
            if first_project:
                return first_project
            return redirect("preview", username=request.user.username)
        else:
            logger.warning(
                "Builder validation failed for user %s: personal=%s skills=%s education=%s "
                "experience=%s projects=%s links=%s creators=%s",
                request.user.pk, personal_form.errors, skill_formset.errors,
                education_formset.errors, experience_formset.errors,
                project_formset.errors, link_formset.errors, creator_formset.errors,
            )
            activation.track(
                request.user, 'builder_save_failed', flow='builder',
                sections=_invalid_sections(
                    identity=personal_form, skills=skill_formset, education=education_formset,
                    experience=experience_formset, projects=project_formset,
                    links=link_formset, creators=creator_formset,
                ),
            )
            from django.contrib import messages
            error_msg = ("يرجى تصحيح الأخطاء المظللة في ملفك المهني."
                         if arabic else
                         "Please correct the highlighted errors in your portfolio.")
            messages.error(request, error_msg)

    else:
        initial = _portfolio_initial_data(request.user)

        personal_form = PersonalInfoForm(initial=onboarding.personal_initial(
            request.user, PersonalInfo.objects.filter(user=request.user).first(), arabic,
        ))

        # No blank placeholder rows: an empty section shows its empty state and an Add button.
        skill_formset = SkillFormSetUpdate(initial=initial["skills"], prefix="skills")
        education_formset = EducationFormSetUpdate(initial=initial["education"], prefix="education")
        experience_formset = ExperienceFormSetUpdate(initial=initial["experience"], prefix="experience")
        project_formset = ProjectFormSetUpdate(initial=initial["projects"], prefix="projects", form_kwargs={"user": request.user, "arabic": arabic})
        project_category_formset = ProjectCategoryFormSetUpdate(initial=initial["project_categories"], prefix="project_categories")
        link_formset = LinkFormSetUpdate(initial=initial["links"], prefix="links")
        creator_formset = CreatorFormSetUpdate(initial=initial["creators"], prefix="creators")

    profile = getattr(request.user, 'profile', None)

    from core.section_order import (
        normalize_category,
        resolve_section_layout,
        presets_for,
        section_layout_supported,
    )
    import json as _json
    _cat_name = (normalize_category(profile.theme.category.name)
                 if profile and profile.theme and profile.theme.category else None)
    # resolve_section_layout auto-derives the theme from profile.theme, so
    # themes with per-theme defaults (minimal, categories) resolve correctly.
    section_layout = resolve_section_layout(profile, _cat_name)
    section_rows = section_layout['sections']
    section_visibility_json = _json.dumps(section_layout.get('sections', []))
    # The layout panel only ships for themes whose public template includes
    # the section_layout_css block.
    section_layout_enabled = section_layout_supported(_cat_name, section_layout_theme_name(profile))
    section_presets = presets_for(_cat_name, section_layout_theme_name(profile)) if section_layout_enabled else []

    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "project_category_formset": project_category_formset,
        "link_formset": link_formset,
        "creator_formset": creator_formset,
        "reviews": ClientReview.objects.filter(user=request.user).order_by('-created_at'),
        "category": profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "theme",
        "theme_name": profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default",
        "show_project_images": (f"{profile.theme.category.name.lower()}_{profile.theme.name.lower()}".replace(" ", "_") not in ['video_editor_reels', 'video_editor_creative_reels', 'developer_creative']) if profile and profile.theme and profile.theme.category else True,
        "section_layout": section_layout,
        "section_rows": section_rows,
        "section_visibility_json": section_visibility_json,
        "is_custom_layout": section_layout['custom'],
        "default_section_order": section_layout['default_order'],
        "section_layout_enabled": section_layout_enabled,
        "section_presets": section_presets,
        "is_arabic_page": arabic,
        **_page_context(request, arabic),
    }

    if arabic:
        return render(request, 'dashboard/arabic_builder_v2.html', context)

    template_name = 'dashboard/builder.html'
    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        specific_template = f"portfolios/{category}/builder_{category}_{theme_name}.html"
        from django.template.loader import get_template
        from django.template import TemplateDoesNotExist
        try:
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            pass

    return render(request, template_name, context)


@login_required
def update_portfolio_view(request):
    return _update_flow(request)


def section_layout_theme_name(profile):
    """Normalized theme slug ('minimal', 'creative', ...) or '' when unset."""
    if profile is not None and profile.theme is not None and profile.theme.name:
        return profile.theme.name.lower().strip().replace(' ', '_')
    return ''


@login_required(login_url='arabic_signin')
def arabic_update_portfolio_view(request):
    """Arabic (RTL) twin of update_portfolio_view served at /ar/update/."""
    return _update_flow(request, arabic=True)


def _update_flow(request, arabic=False):
    user = request.user

    if request.method == "GET":
        onboarding.ensure_default_theme(user)
        activation.track_reveal_action(request)

    # helper for existing data
    personal_info = PersonalInfo.objects.filter(user=user).first()

    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST, request.FILES) # Start with POST data

        skill_formset = SkillFormSetUpdate(request.POST, prefix="skills")
        education_formset = EducationFormSetUpdate(request.POST, prefix="education")
        experience_formset = ExperienceFormSetUpdate(request.POST, prefix="experience")
        project_formset = ProjectFormSetUpdate(request.POST, request.FILES, prefix="projects", form_kwargs={"user": request.user, "arabic": arabic})
        project_category_formset = ProjectCategoryFormSetUpdate(request.POST, request.FILES, prefix="project_categories")
        link_formset = LinkFormSetUpdate(request.POST, prefix="links")
        creator_formset = CreatorFormSetUpdate(request.POST, request.FILES, prefix="creators")

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
            and creator_formset.is_valid()
        ):
            had_projects = Project.objects.filter(user=user).exists()
            with activation.source('builder'):
                save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset, arabic=arabic)
            activation.track(
                user, 'builder_saved', flow='update',
                projects=Project.objects.filter(user=user).count(),
            )
            services.publish_if_paid(user)

            first_project = _first_project_redirect(request, had_projects, arabic)
            if first_project:
                return first_project
            return redirect("arabic_dashboard" if arabic else "dashboard")
        else:
            logger.warning(
                "Update portfolio validation failed for user %s: personal=%s skills=%s "
                "education=%s experience=%s projects=%s links=%s creators=%s",
                request.user.pk, personal_form.errors, skill_formset.errors,
                education_formset.errors, experience_formset.errors,
                project_formset.errors, link_formset.errors, creator_formset.errors,
            )
            activation.track(
                user, 'builder_save_failed', flow='update',
                sections=_invalid_sections(
                    identity=personal_form, skills=skill_formset, education=education_formset,
                    experience=experience_formset, projects=project_formset,
                    links=link_formset, creators=creator_formset,
                ),
            )
            from django.contrib import messages
            error_msg = ("تعذر حفظ التغييرات. يرجى التحقق من الأخطاء في النموذج."
                         if arabic else
                         "Could not save changes. Please check the form for errors.")
            messages.error(request, error_msg)

    else:
        # Pre-fill forms with existing data
        initial = _portfolio_initial_data(user)

        # Personal Info (name/title are pre-filled from signup for brand-new users)
        personal_form = PersonalInfoForm(initial=onboarding.personal_initial(user, personal_info, arabic))

        skill_formset = SkillFormSetUpdate(initial=initial["skills"], prefix="skills")
        education_formset = EducationFormSetUpdate(initial=initial["education"], prefix="education")
        experience_formset = ExperienceFormSetUpdate(initial=initial["experience"], prefix="experience")
        project_formset = ProjectFormSetUpdate(initial=initial["projects"], prefix="projects", form_kwargs={"user": request.user, "arabic": arabic})
        project_category_formset = ProjectCategoryFormSetUpdate(initial=initial["project_categories"], prefix="project_categories")
        link_formset = LinkFormSetUpdate(initial=initial["links"], prefix="links")
        creator_formset = CreatorFormSetUpdate(initial=initial["creators"], prefix="creators")

    profile = getattr(request.user, 'profile', None)

    from core.section_order import (
        normalize_category,
        resolve_section_layout,
        presets_for,
        section_layout_supported,
    )
    import json as _json
    _cat_name = (normalize_category(profile.theme.category.name)
                 if profile and profile.theme and profile.theme.category else None)
    section_layout = resolve_section_layout(profile, _cat_name)
    section_rows = section_layout['sections']
    section_visibility_json = _json.dumps(section_layout.get('sections', []))
    section_layout_enabled = section_layout_supported(_cat_name, section_layout_theme_name(profile))
    section_presets = presets_for(_cat_name, section_layout_theme_name(profile)) if section_layout_enabled else []

    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "project_category_formset": project_category_formset,
        "link_formset": link_formset,
        "creator_formset": creator_formset,
        "reviews": ClientReview.objects.filter(user=request.user).order_by('-created_at'),
        "is_update": True,
        "category": profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "theme",
        "theme_name": profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default",
        "show_project_images": (f"{profile.theme.category.name.lower()}_{profile.theme.name.lower()}".replace(" ", "_") not in ['video_editor_reels', 'video_editor_creative_reels', 'developer_creative']) if profile and profile.theme and profile.theme.category else True,
        "section_layout": section_layout,
        "section_rows": section_rows,
        "section_visibility_json": section_visibility_json,
        "is_custom_layout": section_layout['custom'],
        "default_section_order": section_layout['default_order'],
        "section_layout_enabled": section_layout_enabled,
        "section_presets": section_presets,
        "is_arabic_page": arabic,
        **_page_context(request, arabic),
    }

    if arabic:
        return render(request, 'dashboard/arabic_builder_v2.html', context)

    template_name = 'dashboard/builder.html'
    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        specific_template = f"portfolios/{category}/builder_{category}_{theme_name}.html"
        from django.template.loader import get_template
        from django.template import TemplateDoesNotExist
        try:
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            pass

    return render(request, template_name, context)


def _portfolio_initial_data(user):
    """Build formset initial data (with DB ids) so existing rows are updated in place."""
    initial = {
        key: [kind.to_initial(row) for row in kind.model.objects.filter(user=user)]
        for key, kind in services.KINDS.items()
    }
    initial["project_categories"] = [{
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "thumbnail": c.thumbnail,
    } for c in ProjectCategory.objects.filter(user=user)]
    return initial



@transaction.atomic
def save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset=None, arabic=False):
    """Save the whole builder form. Collections are saved separately, over AJAX."""
    user = request.user
    # The page sets title_confirmed=1 once the user types in the title or keeps the default.
    services.save_personal(user, personal_form.cleaned_data,
                          confirm_title=request.POST.get("title_confirmed") == "1")
    categories = services.category_map(user)
    for key, formset in (
        ("skills", skill_formset),
        ("education", education_formset),
        ("experience", experience_formset),
        ("projects", project_formset),
        ("links", link_formset),
        ("creators", creator_formset),
    ):
        services.save_formset(user, key, formset, categories, arabic=arabic)
    services.ensure_payment_row(user)
