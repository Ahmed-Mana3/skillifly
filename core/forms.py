from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import Profile, Experience, Education, Skill, Project, Link

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
