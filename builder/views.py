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
from datetime import date

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
)

@login_required
@require_POST
def ajax_save_section_layout(request):
    """AJAX endpoint to save/reset the portfolio section order and visibility."""
    from core.section_order import (
        normalize_section_order,
        normalize_section_visibility,
        supported_keys,
    )
    import json

    profile, _ = Profile.objects.get_or_create(user=request.user)
    category = (
        profile.theme.category.name.lower().replace(' ', '_')
        if profile.theme and profile.theme.category
        else 'video_editor'
    )

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

    allowed = set(supported_keys(category))

    invalid_order = [k for k in order_candidates if k not in allowed]
    if invalid_order:
        return JsonResponse({'success': False, 'invalid_keys': invalid_order}, status=400)

    order_list = normalize_section_order(order_candidates, category)

    visibility_map = normalize_section_visibility(raw_visibility, category)
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

    profile.section_order = order_list
    profile.section_visibility = visibility_map
    profile.save(update_fields=['section_order', 'section_visibility'])
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


def _translate_project_video_types(project_formset):
    """Swap video_type choice labels for the Arabic UI (values unchanged)."""
    for form in project_formset.forms + [project_formset.empty_form]:
        if 'video_type' in form.fields:
            form.fields['video_type'].choices = [
                ('long', 'فيديو طويل'),
                ('reel', 'ريلز / فيديو قصير'),
            ]


def _builder_flow(request, arabic=False):
    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST, request.FILES)

        skill_formset = SkillFormSet(request.POST, prefix="skills")
        education_formset = EducationFormSet(request.POST, prefix="education")
        experience_formset = ExperienceFormSet(request.POST, prefix="experience")
        project_formset = ProjectFormSet(request.POST, request.FILES, prefix="projects")
        project_category_formset = ProjectCategoryFormSet(request.POST, request.FILES, prefix="project_categories")
        link_formset = LinkFormSet(request.POST, prefix="links")
        creator_formset = CreatorFormSet(request.POST, request.FILES, prefix="creators")

        if arabic:
            _translate_project_video_types(project_formset)

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
            and creator_formset.is_valid()
        ):

            save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset)

            # Set profile to public if user has payment
            payment = UserPayment.objects.filter(user=request.user, status='paid').last()
            if payment and payment.is_active:
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()

            return redirect("preview", username=request.user.username)
        else:
            print("--- BUILDER VALIDATION ERRORS ---")
            print(f"Personal Form Errors: {personal_form.errors}")
            print(f"Skill Errors: {skill_formset.errors}")
            print(f"Education Errors: {education_formset.errors}")
            print(f"Experience Errors: {experience_formset.errors}")
            print(f"Project Errors: {project_formset.errors}")
            print(f"Link Errors: {link_formset.errors}")
            from django.contrib import messages
            error_msg = ("يرجى تصحيح الأخطاء المظللة في ملفك المهني."
                         if arabic else
                         "Please correct the highlighted errors in your portfolio.")
            messages.error(request, error_msg)

    else:
        initial = _portfolio_initial_data(request.user)

        personal_form = PersonalInfoForm()

        skill_formset = SkillFormSet(initial=initial["skills"], prefix="skills")
        education_formset = EducationFormSet(initial=initial["education"], prefix="education")
        experience_formset = ExperienceFormSet(initial=initial["experience"], prefix="experience")
        project_formset = ProjectFormSet(initial=initial["projects"], prefix="projects")
        project_category_formset = ProjectCategoryFormSet(initial=initial["project_categories"], prefix="project_categories")
        link_formset = LinkFormSet(initial=initial["links"], prefix="links")
        creator_formset = CreatorFormSet(initial=initial["creators"], prefix="creators")

        if arabic:
            _translate_project_video_types(project_formset)

    profile = getattr(request.user, 'profile', None)

    from core.section_order import resolve_section_layout
    import json as _json
    _cat_name = profile.theme.category.name.lower() if profile and profile.theme and profile.theme.category else None
    section_layout = resolve_section_layout(profile, _cat_name)
    section_rows = section_layout['sections']
    section_visibility_json = _json.dumps(section_layout.get('sections', []))

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
        "is_arabic_page": arabic,
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


@login_required(login_url='arabic_signin')
def arabic_update_portfolio_view(request):
    """Arabic (RTL) twin of update_portfolio_view served at /ar/update/."""
    return _update_flow(request, arabic=True)


def _update_flow(request, arabic=False):
    user = request.user

    # helper for existing data
    personal_info = PersonalInfo.objects.filter(user=user).first()

    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST, request.FILES) # Start with POST data

        skill_formset = SkillFormSetUpdate(request.POST, prefix="skills")
        education_formset = EducationFormSetUpdate(request.POST, prefix="education")
        experience_formset = ExperienceFormSetUpdate(request.POST, prefix="experience")
        project_formset = ProjectFormSetUpdate(request.POST, request.FILES, prefix="projects")
        project_category_formset = ProjectCategoryFormSetUpdate(request.POST, request.FILES, prefix="project_categories")
        link_formset = LinkFormSetUpdate(request.POST, prefix="links")
        creator_formset = CreatorFormSetUpdate(request.POST, request.FILES, prefix="creators")

        if arabic:
            _translate_project_video_types(project_formset)

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
            and creator_formset.is_valid()
        ):
            save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset)
            # Set profile to public if user has active payment
            payment = UserPayment.objects.filter(user=request.user, status='paid').last()
            if payment and payment.is_active:
                profile = Profile.objects.filter(user=user).first()
                if profile:
                    profile.is_public = True
                    profile.save()

            return redirect("arabic_dashboard" if arabic else "dashboard")
        else:
            print("--- UPDATE PORTFOLIO VALIDATION ERRORS ---")
            print(f"Personal Form Errors: {personal_form.errors}")
            print(f"Skill Errors: {skill_formset.errors}")
            print(f"Education Errors: {education_formset.errors}")
            print(f"Experience Errors: {experience_formset.errors}")
            print(f"Project Errors: {project_formset.errors}")
            print(f"Link Errors: {link_formset.errors}")
            from django.contrib import messages
            error_msg = ("تعذر حفظ التغييرات. يرجى التحقق من الأخطاء في النموذج."
                         if arabic else
                         "Could not save changes. Please check the form for errors.")
            messages.error(request, error_msg)

    else:
        # Pre-fill forms with existing data
        initial = _portfolio_initial_data(user)

        # Personal Info
        initial_personal = {}
        if personal_info:
            initial_personal = {
                'fullname': personal_info.full_name,
                'title': personal_info.title,
                'email': personal_info.email,
                'phone': personal_info.phone,
                'bio': personal_info.bio,
                'booking_url': personal_info.booking_url,
            }
        personal_form = PersonalInfoForm(initial=initial_personal)

        skill_formset = SkillFormSetUpdate(initial=initial["skills"], prefix="skills")
        education_formset = EducationFormSetUpdate(initial=initial["education"], prefix="education")
        experience_formset = ExperienceFormSetUpdate(initial=initial["experience"], prefix="experience")
        project_formset = ProjectFormSetUpdate(initial=initial["projects"], prefix="projects")
        project_category_formset = ProjectCategoryFormSetUpdate(initial=initial["project_categories"], prefix="project_categories")
        link_formset = LinkFormSetUpdate(initial=initial["links"], prefix="links")
        creator_formset = CreatorFormSetUpdate(initial=initial["creators"], prefix="creators")

        if arabic:
            _translate_project_video_types(project_formset)

    profile = getattr(request.user, 'profile', None)

    from core.section_order import resolve_section_layout
    import json as _json
    _cat_name = profile.theme.category.name.lower() if profile and profile.theme and profile.theme.category else None
    section_layout = resolve_section_layout(profile, _cat_name)
    section_rows = section_layout['sections']
    section_visibility_json = _json.dumps(section_layout.get('sections', []))

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
        "is_arabic_page": arabic,
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
    from core.models import ProjectCategory

    skills = [{"id": s.id, "skill": s.name} for s in Skill.objects.filter(user=user)]

    education = [{
        "id": e.id,
        "school": e.school,
        "degree": e.degree,
        "field": e.field,
        "year": e.grade_year.year,
    } for e in Education.objects.filter(user=user)]

    experience = []
    for e in Experience.objects.filter(user=user):
        experience.append({
            "id": e.id,
            "title": e.title,
            "company": e.company,
            "start": e.start_date.strftime('%Y-%m') if e.start_date else '',
            "end": e.end_date.strftime('%Y-%m') if e.end_date else '',
            "description": e.details,
        })

    projects = [{
        "id": p.id,
        "name": p.title,
        "url": p.url,
        "description": p.details,
        "video_type": p.video_type,
        "thumbnail": p.image,
        "category_id": p.category_id,
    } for p in Project.objects.filter(user=user)]

    project_categories = [{
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "thumbnail": c.thumbnail,
    } for c in ProjectCategory.objects.filter(user=user)]

    links = [{"id": l.id, "name": l.platform, "url": l.url} for l in Link.objects.filter(user=user)]

    creators = [{
        "id": c.id,
        "name": c.name,
        "image": c.image,
        "url": c.url,
    } for c in Creator.objects.filter(user=user)]

    return {
        "skills": skills,
        "education": education,
        "experience": experience,
        "projects": projects,
        "project_categories": project_categories,
        "links": links,
        "creators": creators,
    }


def _category_for(category_id, category_mapping):
    if not category_id:
        return None
    try:
        return category_mapping.get(int(category_id))
    except (TypeError, ValueError):
        return None


def _parse_month_year(date_str):
    if not date_str:
        return None
    try:
        y, m = map(int, date_str.split("-"))
        return date(y, m, 1)
    except (ValueError, AttributeError):
        return None


def _update_or_create(existing_map, submitted_ids, data, model_cls, user, fields):
    """Update existing rows by id, create new ones, then delete rows no longer submitted."""
    row_id = data.get("id")
    if row_id and row_id in existing_map:
        instance = existing_map[row_id]
        has_changed = False
        for key, value in fields.items():
            if getattr(instance, key) != value:
                setattr(instance, key, value)
                has_changed = True
        if has_changed:
            instance.save()
        submitted_ids.add(row_id)
    else:
        model_cls.objects.create(user=user, **fields)


@transaction.atomic
def save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset=None):
    personal_data = personal_form.cleaned_data

    skills = [
        f.cleaned_data
        for f in skill_formset
        if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
    ]

    education = [
        f.cleaned_data
        for f in education_formset
        if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
    ]

    experience = [
        f.cleaned_data
        for f in experience_formset
        if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
    ]

    projects = [
        f.cleaned_data
        for f in project_formset
        if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
    ]

    links = [
        f.cleaned_data
        for f in link_formset
        if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
    ]

    creators = [
        f.cleaned_data
        for f in creator_formset
        if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
    ]

    personal_info, created = PersonalInfo.objects.update_or_create(
        user=request.user,
        defaults={
            "full_name": personal_data["fullname"],
            "title": personal_data["title"],
            "email": personal_data["email"],
            "phone": personal_data["phone"],
            "bio": personal_data["bio"],
            "booking_url": personal_data.get("booking_url"),
        },
    )

    # Save picture to Profile if provided
    if "picture" in personal_data and personal_data["picture"]:
        profile, p_created = Profile.objects.get_or_create(user=request.user)
        profile.picture = personal_data["picture"]
        profile.save()

    # --- Skills ---
    existing_map = {s.id: s for s in Skill.objects.filter(user=request.user)}
    submitted_ids = set()
    for skill_data in skills:
        _update_or_create(
            existing_map, submitted_ids,
            skill_data, Skill, request.user,
            {"name": skill_data["skill"]},
        )
    for s_id, skill in existing_map.items():
        if s_id not in submitted_ids:
            skill.delete()

    # --- Education ---
    existing_map = {e.id: e for e in Education.objects.filter(user=request.user)}
    submitted_ids = set()
    for edu_data in education:
        _update_or_create(
            existing_map, submitted_ids,
            edu_data, Education, request.user,
            {
                "school": edu_data["school"],
                "degree": edu_data["degree"],
                "field": edu_data["field"],
                "grade_year": date(edu_data["year"], 1, 1),
            },
        )
    for e_id, edu in existing_map.items():
        if e_id not in submitted_ids:
            edu.delete()

    # --- Experience ---
    existing_map = {e.id: e for e in Experience.objects.filter(user=request.user)}
    submitted_ids = set()
    for exp_data in experience:
        start_date = _parse_month_year(exp_data.get("start"))
        end_date = _parse_month_year(exp_data.get("end"))
        _update_or_create(
            existing_map, submitted_ids,
            exp_data, Experience, request.user,
            {
                "title": exp_data["title"],
                "company": exp_data["company"],
                "start_date": start_date or date.today(),
                "end_date": end_date,
                "still_working": not end_date,
                "duration": 0.0,
                "details": exp_data.get("description", ""),
            },
        )
    for e_id, exp in existing_map.items():
        if e_id not in submitted_ids:
            exp.delete()

    # --- Project Categories (read from DB, saved via AJAX) ---
    from core.models import ProjectCategory
    category_mapping = {c.id: c for c in ProjectCategory.objects.filter(user=request.user)}

    # --- Projects ---
    existing_map = {p.id: p for p in Project.objects.filter(user=request.user)}
    submitted_ids = set()
    for proj_data in projects:
        new_image = proj_data.get("thumbnail")
        fields = {
            "title": proj_data["name"],
            "url": proj_data.get("url"),
            "details": proj_data.get("description"),
            "video_type": proj_data.get("video_type", "long"),
            "category": _category_for(proj_data.get("category_id"), category_mapping),
        }
        if new_image:
            fields["image"] = new_image
        _update_or_create(
            existing_map, submitted_ids,
            proj_data, Project, request.user, fields,
        )
    for p_id, project in existing_map.items():
        if p_id not in submitted_ids:
            project.delete()

    # --- Links ---
    existing_map = {l.id: l for l in Link.objects.filter(user=request.user)}
    submitted_ids = set()
    for link_data in links:
        _update_or_create(
            existing_map, submitted_ids,
            link_data, Link, request.user,
            {
                "platform": link_data["name"],
                "url": link_data["url"],
            },
        )
    for l_id, link in existing_map.items():
        if l_id not in submitted_ids:
            link.delete()

    # --- Creators ---
    existing_map = {c.id: c for c in Creator.objects.filter(user=request.user)}
    submitted_ids = set()
    for cr_data in creators:
        fields = {
            "name": cr_data["name"],
            "url": cr_data.get("url"),
        }
        new_image = cr_data.get("image")
        if new_image:
            fields["image"] = new_image
        _update_or_create(
            existing_map, submitted_ids,
            cr_data, Creator, request.user, fields,
        )
    for c_id, creator in existing_map.items():
        if c_id not in submitted_ids:
            creator.delete()

    # Ensure a UserPayment record exists
    if not UserPayment.objects.filter(user=request.user).exists():
        UserPayment.objects.create(user=request.user)


