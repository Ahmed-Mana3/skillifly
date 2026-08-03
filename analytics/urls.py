from django.urls import path
from . import views

urlpatterns = [
    path('api/track/', views.track_analytics, name='track_analytics'),
    path('dashboard/analytics/', views.analytics_dashboard, name='analytics'),
    path('ar/dashboard/analytics/', views.arabic_analytics_dashboard, name='arabic_analytics'),
    path('user-activity/', views.user_activity_report, name='user_activity_report'),
]
