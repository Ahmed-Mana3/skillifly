from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from core.models import Profile, PersonalInfo, Experience, Education, Skill, Project, Link, SEOSettings, CustomDomain, DiscountCode, SiteSettings, School
from django import forms
from django.forms import formset_factory, BaseFormSet
from datetime import datetime

User = get_user_model()  

class RegisterForm(UserCreationForm):
    """Editor signup.

    Accepts either the classic first/last name + confirm-password fields or the
    short form (one ``full_name`` field, no confirm-password). Both post paths
    validate identically, so the legacy template keeps working.
    """

    full_name = forms.CharField(
        required=False,
        max_length=300,
        widget=forms.TextInput(
            attrs={
                "id": "full_name",
                "placeholder": "Sara Ali",
                "autocomplete": "name",
                "class": "form-control",
            }
        )
    )

    first_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "id": "first_name",
                "placeholder": "John Doe",
                "class": "form-control",
            }
        )
    )

    last_name = forms.CharField(
        required=False,
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
        help_text="Your portfolio will be at: skillifly.cloud/yourusername"
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
        required=False,  # the short signup form has no confirm field; see clean()
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

    def clean(self):
        cleaned = super().clean()

        # Name: either first/last, or one "full name" split at the first space.
        first = (cleaned.get('first_name') or '').strip()
        last = (cleaned.get('last_name') or '').strip()
        full = (cleaned.get('full_name') or '').strip()
        if full and not first:
            first, _, rest = full.partition(' ')
            last = last or rest.strip()
        if not first:
            # Show the error on a field the posted form actually renders.
            self.add_error('first_name' if 'first_name' in self.data else 'full_name',
                           'Please enter your name.')
        cleaned['first_name'], cleaned['last_name'] = first[:150], last[:150]

        # No confirm field posted: Django's password-strength check and save() both read
        # password2, so mirror password1 into it or weak passwords would skip validation.
        if not cleaned.get('password2') and cleaned.get('password1'):
            cleaned['password2'] = cleaned['password1']
        return cleaned

    def add_error(self, field, error):
        # The short form doesn't render password2, so surface its errors on password1.
        if field == 'password2' and not (self.data.get('password2') or '').strip():
            field = 'password1'
        super().add_error(field, error)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        # Case-insensitive, and a friendly message instead of the model's "Custom user with this Email already exists."
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.', code='exists')
        return email

    def clean_username(self):
        from django.conf import settings
        username = super().clean_username()
        # A username equal to a site route (e.g. "welcome") would hide the portfolio.
        if (username or '').lower() in settings.RESERVED_USERNAMES:
            raise ValidationError('This username is reserved. Please choose another.', code='reserved')
        return username

class ClientRegisterForm(forms.Form):
    """Minimal signup form for client accounts (no username, no OTP)."""
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "client_name",
                "placeholder": "Your name",
                "class": "form-control",
                "autocomplete": "name",
            }
        ),
        label="Name",
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "id": "client_email",
                "placeholder": "you@example.com",
                "class": "form-control",
                "autocomplete": "email",
            }
        )
    )

    password = forms.CharField(
        required=True,
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "id": "client_password",
                "placeholder": "Create a password",
                "class": "form-control",
                "autocomplete": "new-password",
            }
        )
    )

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise ValidationError("This field is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists. Please sign in instead.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password, user=None)
        return password


class SchoolAdminRegisterForm(forms.Form):
    """Signup form for school admin accounts — school, name, email, password."""
    school = forms.ModelChoiceField(
        queryset=School.objects.all(),
        required=True,
        empty_label="Select your school",
        widget=forms.Select(
            attrs={
                "id": "school_select",
                "class": "form-control",
            }
        ),
        label="School",
    )
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "school_admin_name",
                "placeholder": "Your name",
                "class": "form-control",
                "autocomplete": "name",
            }
        ),
        label="Name",
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "id": "school_admin_email",
                "placeholder": "you@example.com",
                "class": "form-control",
                "autocomplete": "email",
            }
        )
    )
    password = forms.CharField(
        required=True,
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "id": "school_admin_password",
                "placeholder": "Create a password",
                "class": "form-control",
                "autocomplete": "new-password",
            }
        )
    )

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise ValidationError("This field is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists. Please sign in instead.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password, user=None)
        return password


class ChooseSchoolForm(forms.Form):
    """Form for Google OAuth school admins to pick their school after signup."""
    school = forms.ModelChoiceField(
        queryset=School.objects.all(),
        required=True,
        empty_label="Select your school",
        widget=forms.Select(
            attrs={
                "id": "school_select",
                "class": "form-control",
            }
        ),
        label="School",
    )

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
            # Signing in with an email: swap in the account's username, because
            # AuthenticationForm.clean() authenticates with cleaned_data['username'].
            user = user_for_login(username)
            if user is not None:
                self.cleaned_data['username'] = user.username

        return super().clean()


def user_for_login(identifier):
    """The account a sign-in identifier (username or email) points at, or None.

    Emails match case-insensitively, but an exact match wins if two old accounts
    differ only by case. Usernames match exactly, like the auth backend.
    """
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    if '@' in identifier:
        return (User.objects.filter(email=identifier).first()
                or User.objects.filter(email__iexact=identifier).order_by('pk').first())
    return User.objects.filter(username=identifier).first()



# =========================
# Reviews (ModelForm)
# =========================
from core.models import Review, ClientReview

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['user_name', 'user_title', 'user_image', 'content', 'rating']
        widgets = {
            'user_name': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'Your Name'}),
            'user_title': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. YouTuber'}),
            'user_image': forms.ClearableFileInput(attrs={'class': 'sf-input', 'accept': 'image/*'}),
            'content': forms.Textarea(attrs={'class': 'sf-input', 'placeholder': 'Your Review...', 'rows': 4}),
            'rating': forms.HiddenInput(attrs={'class': 'sf-rating-value'}),
        }

class ClientReviewForm(forms.ModelForm):
    class Meta:
        model = ClientReview
        fields = ['user_name', 'user_title', 'user_image', 'content', 'rating']
        widgets = {
            'user_name': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'Your Name'}),
            'user_title': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. YouTuber'}),
            'user_image': forms.ClearableFileInput(attrs={'class': 'sf-input', 'accept': 'image/*'}),
            'content': forms.Textarea(attrs={'class': 'sf-input', 'placeholder': 'Your Review...', 'rows': 4}),
            'rating': forms.HiddenInput(attrs={'class': 'sf-rating-value'}),
        }

from core.models import SEOSettings

class ReviewAvatarForm(forms.Form):
    """Lets a portfolio owner upload/replace the avatar shown for a client review."""
    user_image = forms.ImageField(
        widget=forms.FileInput(attrs={'accept': 'image/*'}),
    )

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

class DiscountCodeForm(forms.ModelForm):
    class Meta:
        model = DiscountCode
        fields = ['code', 'discount_percentage', 'owner', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. SAVE50'}),
            'discount_percentage': forms.NumberInput(attrs={'class': 'sf-input', 'min': 0, 'max': 100}),
            'owner': forms.Select(attrs={'class': 'sf-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500'}),
        }

class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ['banner_discount_percentage', 'banner_coupon_code', 'banner_is_active']
        widgets = {
            'banner_discount_percentage': forms.NumberInput(attrs={'class': 'sf-input', 'min': 0, 'max': 100}),
            'banner_coupon_code': forms.TextInput(attrs={'class': 'sf-input', 'placeholder': 'e.g. WELCOME2026'}),
            'banner_is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500'}),
        }


class ShowcaseSettingsForm(forms.ModelForm):
    """Homepage hero-showcase controls (the fake-browser tabs on the landing page).

    showcase_themes arrives as a JSON array string from the manage UI's hidden
    input (ordered list of enabled theme slugs) and is re-parsed by the view —
    it stays a CharField here on purpose so form.save() never writes the raw
    string into the JSONField column. Portfolio overrides are likewise handled
    by the view from a dedicated hidden field.
    """

    showcase_themes = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'showcase_themes_input'}),
        help_text='JSON array of theme slugs in display order (managed by the UI).',
    )

    class Meta:
        model = SiteSettings
        fields = ['showcase_default_theme', 'showcase_auto_rotate', 'showcase_zoom']
        widgets = {
            'showcase_default_theme': forms.Select(attrs={'class': 'sf-input'}),
            'showcase_auto_rotate': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500'}),
            'showcase_zoom': forms.NumberInput(attrs={'class': 'sf-input', 'min': 10, 'max': 100}),
        }

    def __init__(self, *args, theme_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        if theme_choices:
            self.fields['showcase_default_theme'].choices = theme_choices
