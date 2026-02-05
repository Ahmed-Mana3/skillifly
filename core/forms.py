from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import Profile, PersonalInfo, Experience, Education, Skill, Project, Link
from django import forms
from django.forms import formset_factory, BaseFormSet
from django.core.validators import RegexValidator
from datetime import datetime

User = get_user_model()  

class RegisterForm(UserCreationForm):
    first_name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "first_name",
                "placeholder": "John Doe",
                "class": "form-control",
            }
        )
    )

    last_name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "last_name",
                "placeholder": "Doe",
                "class": "form-control",
            }
        )
    )

    username = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "username",
                "placeholder": "johndoe",
                "class": "form-control",
            }
        ),
        help_text="Your portfolio will be at: portfoliobuilder.com/yourusername"
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "id": "email",
                "placeholder": "you@example.com",
                "class": "form-control",
            }
        )
    )

    password1 = forms.CharField(
        required=True,
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "id": "password1",
                "placeholder": "••••••••",
                "class": "form-control",
            }
        )
    )

    password2 = forms.CharField(
        required=True,
        label="Confirm Password",
        widget=forms.PasswordInput(
            attrs={
                "id": "password2",
                "placeholder": "••••••••",
                "class": "form-control",
            }
        )
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email"]

class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or Username",
        widget=forms.TextInput(
            attrs={
                "id": "email",
                "placeholder": "you@example.com or username",
                "class": "form-control", 
            }
        )
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "id": "password", 
                "placeholder": "••••••••",
            }
        )
    )
    remember = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                "class": "",
            }
        ),
        label="Remember me"
    )

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            # Check if username is an email
            if '@' in username:
                try:
                    user = User.objects.get(email=username)
                    # Update username to the actual username so super().clean() can authenticate
                    # AuthenticationForm expects the username field to contain the username
                    # If we don't update this, it tries to authenticate with username="email@example.com"
                    # which fails if the backend expects a username.
                    # Note: We are modifying the dictionary that super().clean() reads from.
                    # AuthenticationForm.clean() reads self.cleaned_data.get('username')
                    
                    # We need to ensure we update what AuthenticationForm uses.
                    # AuthenticationForm uses `self.cleaned_data.get("username")`
                    self.cleaned_data['username'] = user.username
                except User.DoesNotExist:
                    # If no user found with this email, let the default authentication fail
                    pass
        
        return super().clean()


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
        required=True,
        widget=forms.EmailInput(attrs={
            "id": "email",
            "placeholder": "john@example.com",
            "required": True,
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


# =========================
# Skills (Formset)
# =========================
class SkillForm(forms.Form):
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
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Computer Science",
            "required": True,
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
# Projects (Formset)
# =========================
class ProjectForm(forms.Form):
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g., Portfolio Builder",
            "required": True,
        })
    )
    url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            "placeholder": "https://example.com",
        })
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "What did you build? What impact did it have?",
        })
    )


# =========================
# Links (Formset)
# =========================
class LinkForm(forms.Form):
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g., GitHub, LinkedIn, Portfolio",
            "required": True,
        })
    )
    url = forms.URLField(
        required=True,
        widget=forms.URLInput(attrs={
            "placeholder": "https://example.com",
            "required": True,
        })
    )


# =========================
# Formset factories
# =========================
SkillFormSet = formset_factory(SkillForm, extra=1, can_delete=True)
EducationFormSet = formset_factory(EducationForm, extra=1, can_delete=True)
ExperienceFormSet = formset_factory(ExperienceForm, extra=1, can_delete=True)
ProjectFormSet = formset_factory(ProjectForm, extra=1, can_delete=True)
LinkFormSet = formset_factory(LinkForm, extra=1, can_delete=True)
