from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from core.models import Profile, PersonalInfo, Experience, Education, Skill, Project, Link, SEOSettings, CustomDomain, DiscountCode, SiteSettings
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
# Reviews (ModelForm)
# =========================
from core.models import Review

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
