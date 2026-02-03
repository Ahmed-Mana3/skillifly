from django.shortcuts import render, redirect
from .forms import RegisterForm, LoginForm
from django.contrib.auth import login, logout
from .models import *

# Create your views here.

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

    return render(request, 'signin.html')


def logout_view(request):
    logout(request)
    message = "please come back ASAP 😥"
    return redirect('login')


def dashboard_view(request):
    """Render the dashboard page"""
    return render(request, 'dashboard.html')


def builder_view(request):
    """Render the portfolio builder page"""
    return render(request, 'builder.html')


def preview_view(request):
    """Render the preview page"""
    return render(request, 'preview.html')


def payment_view(request):
    """Render the payment page"""
    return render(request, 'payment.html')
