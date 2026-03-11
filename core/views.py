from datetime import date
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from datetime import timedelta
from .forms import RegisterForm, LoginForm
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from .models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser, UserPayment
from .forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    LinkFormSet,
    SkillFormSetUpdate,
    EducationFormSetUpdate,
    ExperienceFormSetUpdate,
    ProjectFormSetUpdate,
    LinkFormSetUpdate,
)


def index(request):
    """Render the home/landing page — redirect authenticated users to dashboard"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    portfolios_count = Profile.objects.count()
    themes_count = Theme.objects.count()
    context = {
        'portfolios_count': portfolios_count,
        'themes_count': themes_count,
    }
    return render(request, 'index.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            login(request, form.save())
            return redirect('themes')
        else:
            message = form.errors
    else:
        form = RegisterForm()
        message = None

    context = {
        'message': message,
        'form': form
    }
    return render(request, 'signup.html', context)


def signin_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('themes')
        else:
            message = form.errors
    else:
        form = LoginForm()
        message = None

    context = {
        'message': message,
        'form': form
    }
    return render(request, 'signin.html', context)


def logout_view(request):
    logout(request)
    return redirect('signin')


@login_required
def dashboard_view(request):
    """Render the dashboard page"""
    profile, created = Profile.objects.select_related('user', 'theme__category').get_or_create(user=request.user)
    
    # Calculate subscription days left
    payment = UserPayment.objects.filter(user=request.user, status=True).last()
    days_left = 0
    
    if payment and payment.subscription:
        expiration_date = payment.date + timedelta(days=payment.subscription.days)
        remaining = expiration_date - timezone.now()
        days_left = max(0, remaining.days)
        
    portfolio_url = request.build_absolute_uri(f'/{request.user.username}/')
    context = {
        'profile': profile,
        'days_left': days_left,
        'payment': payment,
        'portfolio_url': portfolio_url,
    }
    return render(request, 'dashboard.html', context)

@login_required
def activate_portfolio(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    # Check for active payment status
    has_active_payment = UserPayment.objects.filter(user=request.user, status=True).exists()
    
    if has_active_payment:
        profile.is_public = not profile.is_public
    else:
        # If no payment, ensure it's private
        profile.is_public = False
        
    profile.save()
    return redirect('dashboard')

@login_required
def themes(request):
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect('signin')
            
        theme_id = request.POST.get('theme')
        theme = get_object_or_404(Theme, id=theme_id)
        
        # Ensure profile exists and save theme
        profile, created = Profile.objects.get_or_create(user=request.user)
        profile.theme = theme
        profile.save()

        # Update usage count
        theme.use_num += 1
        theme.save()

        # If user has no portfolio data yet, send them to the builder first
        has_data = PersonalInfo.objects.filter(user=request.user).exists()
        if not has_data:
            return redirect('builder')
        return redirect('preview', username=request.user.username)
    
    themes = Theme.objects.all()
    categories = Category.objects.all()
    return render(request, 'themes.html', {'themes': themes, 'categories' : categories})

@login_required
def builder_view(request):
    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST)

        skill_formset = SkillFormSet(request.POST, prefix="skills")
        education_formset = EducationFormSet(request.POST, prefix="education")
        experience_formset = ExperienceFormSet(request.POST, prefix="experience")
        project_formset = ProjectFormSet(request.POST, prefix="projects")
        link_formset = LinkFormSet(request.POST, prefix="links")

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
        ):

            save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset)

            return redirect("preview", username=request.user.username)

    else:
 
        personal_form = PersonalInfoForm()

        skill_formset = SkillFormSet(prefix="skills")
        education_formset = EducationFormSet(prefix="education")
        experience_formset = ExperienceFormSet(prefix="experience")
        project_formset = ProjectFormSet(prefix="projects")
        link_formset = LinkFormSet(prefix="links")

    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "link_formset": link_formset,
    }
    return render(request, "builder.html", context)


@login_required
def update_portfolio_view(request):
    user = request.user
    
    # helper for existing data
    personal_info = PersonalInfo.objects.filter(user=user).first()
    
    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST) # Start with POST data
        
        skill_formset = SkillFormSetUpdate(request.POST, prefix="skills")
        education_formset = EducationFormSetUpdate(request.POST, prefix="education")
        experience_formset = ExperienceFormSetUpdate(request.POST, prefix="experience")
        project_formset = ProjectFormSetUpdate(request.POST, prefix="projects")
        link_formset = LinkFormSetUpdate(request.POST, prefix="links")

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
        ):
            save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset)
            return redirect("preview", username=request.user.username)
    
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
            'description': p.details
        } for p in Project.objects.filter(user=user)]
        project_formset = ProjectFormSetUpdate(initial=project_data, prefix="projects")

        # Links
        link_data = [{
            'name': l.platform,
            'url': l.url
        } for l in Link.objects.filter(user=user)]
        link_formset = LinkFormSetUpdate(initial=link_data, prefix="links")

    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "link_formset": link_formset,
        "is_update": True
    }
    return render(request, "builder.html", context)


def save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset):
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

            personal_info, created = PersonalInfo.objects.update_or_create(
                user=request.user,
                defaults={
                    "full_name": personal_data["fullname"],
                    "title": personal_data["title"],
                    "email": personal_data["email"],
                    "phone": personal_data["phone"],
                    "bio": personal_data["bio"],
                },
            )

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

            Project.objects.filter(user=request.user).delete()
            for proj_data in projects:
                Project.objects.create(
                    user=request.user,
                    title=proj_data["name"],
                    url=proj_data.get("url"),
                    details=proj_data.get("description"),
                )

            Link.objects.filter(user=request.user).delete()
            for link_data in links:
                Link.objects.create(
                    user=request.user,
                    platform=link_data["name"],
                    url=link_data["url"],
                )
            
            # Ensure a UserPayment record exists
            if not UserPayment.objects.filter(user=request.user).exists():
                UserPayment.objects.create(user=request.user)


def preview_view(request, username):
    user = get_object_or_404(CustomUser, username=username)
    
    # Increment visit counter
    profile, created = Profile.objects.get_or_create(user=user)
    
    # Visibility Check: Require payment for public access
    has_active_payment = UserPayment.objects.filter(user=user, status=True).exists()
    
    if (not profile.is_public or not has_active_payment) and request.user != user:
        return render(request, '403_private.html', {'username': username}, status=403)

    profile.visits += 1
    profile.save()

    personal_info = PersonalInfo.objects.filter(user=user).select_related('user').first()
    experiences = Experience.objects.filter(user=user).select_related('user')
    education = Education.objects.filter(user=user).select_related('user')
    skills = Skill.objects.filter(user=user).select_related('user')
    projects = Project.objects.filter(user=user).select_related('user')
    links = Link.objects.filter(user=user).select_related('user')

    context = {
        'personal_info': personal_info,
        'experiences': experiences,
        'education': education,
        'skills': skills,
        'projects': projects,
        'links': links,
    }

    # Dynamic template selection based on theme
    template_name = 'developer_minimal.html'  # Default fallback
    profile = getattr(user, 'profile', None)
    
    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        specific_template = f"{category}_{theme_name}.html"
        
        try:
            # Check if temple exists
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            template_name = 'developer_minimal.html'

    return render(request, template_name, context=context)



def payment_view(request):
    """Render the payment page"""
    context = {
        'free_features': [
            '1 portfolio theme',
            'Public portfolio URL',
            'Personal info & skills',
            'Projects showcase',
            'Social links',
        ],
        'pro_features': [
            'All premium themes',
            'Custom domain support',
            'Portfolio analytics',
            'Remove Skillifly branding',
            'Priority support',
            'Unlimited projects',
        ],
        'annual_features': [
            'Everything in Pro',
            '2 months free',
            'Early access to new themes',
            'Dedicated support channel',
            'Export portfolio as PDF',
        ],
    }
    return render(request, 'payment_new.html', context)


# Error handlers
def custom_404_view(request, exception=None):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)


def custom_500_view(request):
    """Custom 500 error handler"""
    return render(request, '500.html', status=500)


def custom_403_view(request, exception=None):
    """Custom 403 error handler"""
    return render(request, '403.html', status=403)


def sitemap_view(request):
    """Return a simple sitemap.xml"""
    users = CustomUser.objects.filter(profile__is_public=True)
    pages = [
        {'loc': request.build_absolute_uri('/'), 'lastmod': timezone.now().date()},
        {'loc': request.build_absolute_uri('/themes/'), 'lastmod': timezone.now().date()},
    ]
    for user in users:
        pages.append({
            'loc': request.build_absolute_uri(f'/@{user.username}/'),
            'lastmod': timezone.now().date()
        })
    
    return render(request, 'sitemap.xml', {'pages': pages}, content_type='application/xml')


def robots_txt_view(request):
    """Return robots.txt"""
    content = "User-agent: *\nDisallow: /admin/\nDisallow: /builder/\nSitemap: " + request.build_absolute_uri('/sitemap.xml')
    from django.http import HttpResponse
    return HttpResponse(content, content_type="text/plain")
