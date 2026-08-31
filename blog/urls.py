from django.urls import path
from . import views

app_name = 'blog'

urlpatterns = [
    path('', views.post_list, name='post_list'),
    # <str:> not <slug:>: Django's slug converter is ASCII-only and would
    # 404 Arabic slugs (the slug helper keeps Arabic when transliteration
    # is unavailable) — those URLs appear in the sitemap and templates.
    path('<str:slug>/', views.post_detail, name='post_detail'),
    path('category/<str:slug>/', views.category_detail, name='category_detail'),
    path('tag/<str:slug>/', views.tag_detail, name='tag_detail'),
]
