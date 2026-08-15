from django import forms
from django.forms import formset_factory
from django.core.validators import RegexValidator
from datetime import datetime

# =========================
# Personal Info (Single Form)
# =========================
class PersonalInfoForm(forms.Form):
    fullname = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "id": "fullname",
            "placeholder": "John Doe",
            "required": True,
            "class": "form-control",
        })
    )

    title = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "id": "title",
            "placeholder": "Full Stack Developer",
            "required": True,
            "class": "form-control",
        })
    )

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            "id": "email",
            "placeholder": "john@example.com",
            "class": "form-control",
        })
    )

    phone = forms.CharField(
        required=False,
        validators=[
            RegexValidator(
                regex=r"^[0-9+\-\s()]{7,20}$",
                message="Enter a valid phone number."
            )
        ],
        widget=forms.TextInput(attrs={
            "id": "phone",
            "type": "tel",
            "placeholder": "+1 (555) 123-4567",
            "class": "form-control",
        })
    )

    bio = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "id": "bio",
            "rows": 5,
            "placeholder": "Tell us about yourself...",
            "class": "form-control",
        })
    )
    booking_url = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "id": "booking_url",
            "placeholder": "skillifly.cloud or https://...",
            "class": "form-control",
        }),
        help_text="Direct link for bookings (e.g., WhatsApp, Calendly, Contra)"
    )

    picture = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            "id": "picture",
            "class": "form-control",
            "accept": "image/*",
        }),
        help_text="Upload a profile picture for themes that support it"
    )

    def clean_booking_url(self):
        url = self.cleaned_data.get('booking_url')
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url


# =========================
# Skills (Formset)
# =========================
class SkillForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    skill = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "class": "skill-input",
            "placeholder": "e.g., Python, JavaScript, UI Design",
            "required": True,
        })
    )


# =========================
# Education (Formset)
# =========================
class EducationForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    school = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Port Said University",
            "required": True,
        })
    )
    degree = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Bachelor's Degree",
            "required": True,
        })
    )
    field = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Computer Science / Visual Arts",
            "required": False,
        })
    )
    year = forms.IntegerField(
        required=True,
        widget=forms.NumberInput(attrs={
            "placeholder": "2024",
            "required": True,
        })
    )

    def clean_year(self):
        year = self.cleaned_data["year"]
        current_year = datetime.now().year + 10  # allow future a bit
        if year < 1950 or year > current_year:
            raise forms.ValidationError("Enter a valid graduation year.")
        return year


# =========================
# Experience (Formset)
# =========================
class ExperienceForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    title = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Full Stack Developer",
            "required": True,
        })
    )
    company = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Tech Company",
            "required": True,
        })
    )
    start = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "type": "month",
            "required": True,
        })
    )
    end = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "type": "month",
            "placeholder": "Leave blank if current",
        })
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Describe your role and achievements...",
        })
    )


# =========================
# Project Categories (Formset)
# =========================
class ProjectCategoryForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput(attrs={"class": "category-id-input"}))
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g., Wedding Videos",
            "required": True,
        })
    )
    thumbnail = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            "accept": "image/*",
            "class": "thumbnail-input",
        })
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 2,
            "placeholder": "Describe this category...",
        })
    )

# =========================
# Projects (Formset)
# =========================
class ProjectForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput(attrs={"class": "project-id-input"}))
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g., Portfolio Builder",
            "required": True,
        })
    )
    url = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "skillifly.cloud",
        })
    )

    def clean_url(self):
        url = self.cleaned_data.get('url')
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "What did you build? What impact did it have?",
        })
    )
    thumbnail = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            "accept": "image/*",
            "class": "thumbnail-input",
        })
    )
    video_type = forms.ChoiceField(
        choices=[('long', 'Long Video'), ('reel', 'Short/Reel')],
        initial='long',
        widget=forms.Select(attrs={"class": "sf-input"})
    )
    category_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"class": "project-category-input category-dropdown"})
    )


# =========================
# Links (Formset)
# =========================
class LinkForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g., GitHub, LinkedIn, Portfolio",
            "required": True,
        })
    )
    url = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "skillifly.cloud",
            "required": True,
        })
    )

    def clean_url(self):
        url = self.cleaned_data.get('url')
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url


# =========================
# Creators (Formset)
# =========================
class CreatorForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Creator Name",
            "required": True,
        })
    )
    image = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            "accept": "image/*",
        })
    )
    url = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Link to profile (optional)",
        })
    )


# =========================
# Formset factories
# =========================
SkillFormSet = formset_factory(SkillForm, extra=1, can_delete=True)
EducationFormSet = formset_factory(EducationForm, extra=1, can_delete=True)
ExperienceFormSet = formset_factory(ExperienceForm, extra=1, can_delete=True)
ProjectFormSet = formset_factory(ProjectForm, extra=1, can_delete=True)
ProjectCategoryFormSet = formset_factory(ProjectCategoryForm, extra=1, can_delete=True)
LinkFormSet = formset_factory(LinkForm, extra=1, can_delete=True)
CreatorFormSet = formset_factory(CreatorForm, extra=1, can_delete=True)

# Formsets for updates (no extra empty forms)
SkillFormSetUpdate = formset_factory(SkillForm, extra=0, can_delete=True)
EducationFormSetUpdate = formset_factory(EducationForm, extra=0, can_delete=True)
ExperienceFormSetUpdate = formset_factory(ExperienceForm, extra=0, can_delete=True)
ProjectFormSetUpdate = formset_factory(ProjectForm, extra=0, can_delete=True)
ProjectCategoryFormSetUpdate = formset_factory(ProjectCategoryForm, extra=0, can_delete=True)
LinkFormSetUpdate = formset_factory(LinkForm, extra=0, can_delete=True)
CreatorFormSetUpdate = formset_factory(CreatorForm, extra=0, can_delete=True)
