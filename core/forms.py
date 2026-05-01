from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from core.models import Profile, PersonalInfo, Experience, Education, Skill, Project, Link, SEOSettings, CustomDomain
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
# Formset factories
# =========================
SkillFormSet = formset_factory(SkillForm, extra=1, can_delete=True)
EducationFormSet = formset_factory(EducationForm, extra=1, can_delete=True)
ExperienceFormSet = formset_factory(ExperienceForm, extra=1, can_delete=True)
ProjectFormSet = formset_factory(ProjectForm, extra=1, can_delete=True)
LinkFormSet = formset_factory(LinkForm, extra=1, can_delete=True)

# Formsets for updates (no extra empty forms)
SkillFormSetUpdate = formset_factory(SkillForm, extra=0, can_delete=True)
EducationFormSetUpdate = formset_factory(EducationForm, extra=0, can_delete=True)
ExperienceFormSetUpdate = formset_factory(ExperienceForm, extra=0, can_delete=True)
ProjectFormSetUpdate = formset_factory(ProjectForm, extra=0, can_delete=True)
LinkFormSetUpdate = formset_factory(LinkForm, extra=0, can_delete=True)
# =========================
# Reviews (ModelForm)
# =========================
from core.models import Review

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['user_name', 'user_title', 'user_image', 'content', 'rating']
        widgets = {
            'user_name': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'Your Name'}),
            'user_title': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. Video Editor'}),
            'user_image': forms.ClearableFileInput(attrs={'class': 'sf-input', 'accept': 'image/*'}),
            'content': forms.Textarea(attrs={'class': 'sf-input', 'placeholder': 'Your Review...', 'rows': 4}),
            'rating': forms.NumberInput(attrs={'class': 'sf-input', 'min': 1, 'max': 5}),
        }

from core.models import SEOSettings

class SEOSettingsForm(forms.ModelForm):
    class Meta:
        model = SEOSettings
        fields = ['meta_title', 'meta_description', 'meta_keywords', 'og_title', 'og_description', 'og_image']
        widgets = {
            'meta_title': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. John Doe | Professional Video Editor'}),
            'meta_description': forms.Textarea(attrs={'class': 'sf-input', 'placeholder': 'A brief description of your portfolio...', 'rows': 3}),
            'meta_keywords': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. video editor, motion graphics, freelancer'}),
            'og_title': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'Social media title'}),
            'og_description': forms.Textarea(attrs={'class': 'sf-input', 'placeholder': 'Social media description...', 'rows': 2}),
            'og_image': forms.ClearableFileInput(attrs={'class': 'sf-input', 'accept': 'image/*'}),
        }

class CustomDomainForm(forms.ModelForm):
    domain = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'sf-input',
            'placeholder': 'e.g. portfolio.yourname.com',
        }),
        help_text="Enter your custom domain without http:// or https://"
    )

    class Meta:
        model = CustomDomain
        fields = ['domain']

    def clean_domain(self):
        domain = self.cleaned_data.get('domain', '').lower().strip()
        # Basic validation: remove http://, https://, and trailing slashes
        domain = domain.replace('http://', '').replace('https://', '').split('/')[0]
        
        if not domain:
            raise forms.ValidationError("Please enter a valid domain name.")
        
        # Prevent people from trying to use the main domain as their custom domain
        main_domains = ['skillifly.cloud', 'localhost', '127.0.0.1']
        if any(domain == d or domain.endswith('.' + d) for d in main_domains):
            raise forms.ValidationError("You cannot use this domain as a custom domain.")
            
        return domain
