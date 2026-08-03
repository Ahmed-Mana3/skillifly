from django.urls import path
from portfolios import views

urlpatterns = [
    path('examples/', views.examples_view, name='examples'),
    path('ar/examples/', views.arabic_examples_view, name='arabic_examples'),

    # Theme preview by theme name/slug
    path('preview/<str:theme_name>/', views.theme_preview_view, name='theme_preview'),
    path('preview/<str:theme_name>', views.theme_preview_view),

    # Portfolio sub-pages — more specific patterns MUST come before the catch-all
    path('<str:username>/reels/', views.portfolio_reels, name='portfolio_reels'),
    path('<str:username>/long-videos/', views.portfolio_long_videos, name='portfolio_long_videos'),
    path('<str:username>/long-videos/<slug:slug>/', views.portfolio_video_detail, name='portfolio_video_detail'),
    path('<str:username>/category/<int:category_id>/', views.portfolio_category_detail, name='portfolio_category_detail'),

    # Catch-all — must remain LAST
    path('<str:username>/', views.preview_view, name='preview'),
]

