from datetime import date
from django.shortcuts import render, get_object_or_404, redirect
from .forms import RegisterForm, LoginForm
from django.contrib.auth import login, logout
from .models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link
from .forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    LinkFormSet,
)


def index(request):
    """Render the home/landing page"""
    return render(request, 'index.html')


def signup_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            login(request, form.save())
            message = "Welcome to skillifly ❤️"
            return redirect('index')
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
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            login(request, form.get_user())
            message = f"welcome back {form.get_user().username}"
            return redirect('index')
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


def dashboard_view(request):
    """Render the dashboard page"""
    return render(request, 'dashboard.html')

def themes(request):
    if request.method == "POST":
        theme_id = request.POST.get('theme')
        category_id = request.POST.get('category')

        category = get_object_or_404(Category, id=category_id)
        theme = get_object_or_404(Theme, id=theme_id)
        
        profile = request.user.profile
        profile.theme = theme
        profile.save()

        theme.use_num += 1
        theme.save()

        return render(request, f'builder_{category.name.lower()}.html')
    
    themes = Theme.objects.all()
    categories = Category.objects.all()
    return render(request, 'themes.html', {'themes': themes, 'categories' : categories})

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
                    grade_year=date(edu_data["year"], 1, 1),  # Assuming 1st Jan of that year
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
                    duration=0.0, # Placeholder or calculate if needed
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

            return redirect("preview")

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


def preview_view(request):
    """Render the preview page"""
    return render(request, 'preview.html')


def payment_view(request):
    """Render the payment page"""
    return render(request, 'payment.html')
