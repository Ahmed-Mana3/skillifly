from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from datetime import date

# Import models from core
from core.models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser, UserPayment, Review, Showcase, SEOSettings, ManualPayment, Creator, ProjectCategory

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
    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST, request.FILES)

        skill_formset = SkillFormSet(request.POST, prefix="skills")
        education_formset = EducationFormSet(request.POST, prefix="education")
        experience_formset = ExperienceFormSet(request.POST, prefix="experience")
        project_formset = ProjectFormSet(request.POST, request.FILES, prefix="projects")
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
            messages.error(request, "Please correct the highlighted errors in your portfolio.")

    else:
 
        personal_form = PersonalInfoForm()

        skill_formset = SkillFormSet(prefix="skills")
        education_formset = EducationFormSet(prefix="education")
        experience_formset = ExperienceFormSet(prefix="experience")
        project_formset = ProjectFormSet(prefix="projects")
        project_category_formset = ProjectCategoryFormSet(prefix="project_categories")
        link_formset = LinkFormSet(prefix="links")
        creator_formset = CreatorFormSet(prefix="creators")

    profile = getattr(request.user, 'profile', None)
    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "project_category_formset": project_category_formset,
        "link_formset": link_formset,
        "creator_formset": creator_formset,
        "reviews": Review.objects.filter(user=request.user).order_by('-created_at'),
        "category": profile.theme.category.name.lower() if profile and profile.theme and profile.theme.category else "theme",
        "theme_name": profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default",
        "show_project_images": (f"{profile.theme.category.name.lower()}_{profile.theme.name.lower()}".replace(" ", "_") not in ['video_editor_reels', 'video_editor_creative_reels', 'developer_creative']) if profile and profile.theme and profile.theme.category else True
    }
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

            return redirect("dashboard")
        else:
            print("--- UPDATE PORTFOLIO VALIDATION ERRORS ---")
            print(f"Personal Form Errors: {personal_form.errors}")
            print(f"Skill Errors: {skill_formset.errors}")
            print(f"Education Errors: {education_formset.errors}")
            print(f"Experience Errors: {experience_formset.errors}")
            print(f"Project Errors: {project_formset.errors}")
            print(f"Link Errors: {link_formset.errors}")
            from django.contrib import messages
            messages.error(request, "Could not save changes. Please check the form for errors.")
    
    else:
        # Pre-fill forms with existing data
        
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

        # Skills
        skills_data = [{'skill': s.name} for s in Skill.objects.filter(user=user)]
        skill_formset = SkillFormSetUpdate(initial=skills_data, prefix="skills")
        
        # Education
        education_data = [{
            'school': e.school,
            'degree': e.degree,
            'field': e.field,
            'year': e.grade_year.year
        } for e in Education.objects.filter(user=user)]
        education_formset = EducationFormSetUpdate(initial=education_data, prefix="education")

        # Experience
        experience_data = []
        for e in Experience.objects.filter(user=user):
            start_str = e.start_date.strftime('%Y-%m') if e.start_date else ''
            end_str = e.end_date.strftime('%Y-%m') if e.end_date else ''
            experience_data.append({
                'title': e.title,
                'company': e.company,
                'start': start_str,
                'end': end_str,
                'description': e.details
            })
        experience_formset = ExperienceFormSetUpdate(initial=experience_data, prefix="experience")

        # Projects
        project_data = [{
            'name': p.title,
            'url': p.url,
            'description': p.details,
            'video_type': p.video_type,
            'thumbnail': p.image,
            'category_id': p.category_id
        } for p in Project.objects.filter(user=user)]
        project_formset = ProjectFormSetUpdate(initial=project_data, prefix="projects")

        # Project Categories
        from core.models import ProjectCategory
        category_data = [{
            'id': c.id,
            'name': c.name,
            'description': c.description,
            'thumbnail': c.thumbnail
        } for c in ProjectCategory.objects.filter(user=user)]
        project_category_formset = ProjectCategoryFormSetUpdate(initial=category_data, prefix="project_categories")

        # Links
        link_data = [{
            'name': l.platform,
            'url': l.url
        } for l in Link.objects.filter(user=user)]
        link_formset = LinkFormSetUpdate(initial=link_data, prefix="links")

        # Creators
        creator_data = [{
            'name': c.name,
            'image': c.image,
            'url': c.url
        } for c in Creator.objects.filter(user=user)]
        creator_formset = CreatorFormSetUpdate(initial=creator_data, prefix="creators")

    profile = getattr(request.user, 'profile', None)
    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "project_category_formset": project_category_formset,
        "link_formset": link_formset,
        "creator_formset": creator_formset,
        "reviews": Review.objects.filter(user=request.user).order_by('-created_at'),
        "is_update": True,
        "category": profile.theme.category.name.lower() if profile and profile.theme and profile.theme.category else "theme",
        "theme_name": profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default",
        "show_project_images": (f"{profile.theme.category.name.lower()}_{profile.theme.name.lower()}".replace(" ", "_") not in ['video_editor_reels', 'video_editor_creative_reels', 'developer_creative']) if profile and profile.theme and profile.theme.category else True
    }
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


def save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset, creator_formset, project_category_formset=None):
            personal_data = personal_form.cleaned_data

            skills = [
                f.cleaned_data["skill"]
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

            Skill.objects.filter(user=request.user).delete()
            for skill_name in skills:
                Skill.objects.create(user=request.user, name=skill_name)

            Education.objects.filter(user=request.user).delete()
            for edu_data in education:
                Education.objects.create(
                    user=request.user,
                    school=edu_data["school"],
                    degree=edu_data["degree"],
                    field=edu_data["field"],
                    grade_year=date(edu_data["year"], 1, 1),  
                )

            Experience.objects.filter(user=request.user).delete()
            for exp_data in experience:
                
                def parse_month_year(date_str):
                    if not date_str:
                        return None
                    try:
                        y, m = map(int, date_str.split("-"))
                        return date(y, m, 1)
                    except (ValueError, AttributeError):
                        return None

                start_date = parse_month_year(exp_data.get("start"))
                end_date = parse_month_year(exp_data.get("end"))
                
                Experience.objects.create(
                    user=request.user,
                    title=exp_data["title"],
                    company=exp_data["company"],
                    start_date=start_date or date.today(),
                    end_date=end_date,
                    still_working=not end_date,
                    duration=0.0,
                    details=exp_data.get("description", ""),
                )

            # Cache existing project images to prevent data loss
            existing_images = {p.title: p.image for p in Project.objects.filter(user=request.user) if p.image}
            
            # --- Project Categories ---
            # Categories are now saved instantly via AJAX, so we just load existing ones from DB
            from core.models import ProjectCategory
            category_mapping = {
                str(c.id): c
                for c in ProjectCategory.objects.filter(user=request.user)
            }
            
            Project.objects.filter(user=request.user).delete()
            for proj_data in projects:
                new_image = proj_data.get("thumbnail")
                # Restore old image if no new one provided and titles match
                if not new_image:
                    new_image = existing_images.get(proj_data["name"])

                cat_obj = None
                if proj_data.get("category_id"):
                    cat_obj = category_mapping.get(str(proj_data["category_id"]))
                    
                Project.objects.create(
                    user=request.user,
                    title=proj_data["name"],
                    url=proj_data.get("url"),
                    details=proj_data.get("description"),
                    video_type=proj_data.get("video_type", "long"),
                    image=new_image,
                    category=cat_obj
                )

            Link.objects.filter(user=request.user).delete()
            for link_data in links:
                Link.objects.create(
                    user=request.user,
                    platform=link_data["name"],
                    url=link_data["url"],
                )
            
            # Cache existing creator images
            existing_creator_images = {c.name: c.image for c in Creator.objects.filter(user=request.user) if c.image}

            Creator.objects.filter(user=request.user).delete()
            for cr_data in creators:
                new_img = cr_data.get("image")
                if not new_img:
                    new_img = existing_creator_images.get(cr_data["name"])
                Creator.objects.create(
                    user=request.user,
                    name=cr_data["name"],
                    image=new_img,
                    url=cr_data.get("url")
                )
            
            # Ensure a UserPayment record exists
            if not UserPayment.objects.filter(user=request.user).exists():
                UserPayment.objects.create(user=request.user)


