from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('themes/', views.themes, name='themes'),
    path('builder/', views.builder_view, name='builder'),
    path('update_portfolio/', views.update_portfolio_view, name='update_portfolio'),
    path('payment/', views.payment_view, name='payment'),
    path('logout/', views.logout_view, name='logout'),
    path('toggle-visibility/', views.activate_portfolio, name='activate_portfolio'),
    path('sitemap.xml', views.sitemap_view, name='sitemap'),
    path('robots.txt', views.robots_txt_view, name='robots_txt'),
    path('<str:username>/', views.preview_view, name='preview'),
]
