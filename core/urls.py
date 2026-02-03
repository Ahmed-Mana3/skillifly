from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('builder/', views.builder_view, name='builder'),
    path('preview/', views.preview_view, name='preview'),
    path('payment/', views.payment_view, name='payment'),
]
