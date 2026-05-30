from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='blog_dashboard'),
    path('create/', views.post_create, name='post_create'),
    path('<int:pk>/edit/', views.post_update, name='post_update'),
    path('<int:pk>/delete/', views.post_delete, name='post_delete'),
    
    # AJAX APIs
    path('api/categories/create/', views.api_create_category, name='api_create_category'),
    path('api/tags/create/', views.api_create_tag, name='api_create_tag'),
]
