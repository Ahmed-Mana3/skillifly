from django.urls import path, include
from core import views

urlpatterns = [
    path('', views.index, name='index'),
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('themes/', views.themes, name='themes'),
    path('dashboard/seo/', views.seo_settings_view, name='seo_settings'),
    path('dashboard/domain/', views.custom_domain_view, name='custom_domain'),
    path('dashboard/analytics/', views.analytics_dashboard, name='analytics'),
    path('api/track/', views.track_analytics, name='track_analytics'),

    path('logout/', views.logout_view, name='logout'),
    path('toggle-visibility/', views.activate_portfolio, name='activate_portfolio'),
    path('sitemap.xml', views.sitemap_view, name='sitemap'),
    path('robots.txt', views.robots_txt_view, name='robots_txt'),
    path('export/pdf/start/', views.export_pdf_start, name='export_pdf_start'),
    path('export/pdf/status/<int:job_id>/', views.export_pdf_status, name='export_pdf_status'),
    path('export/pdf/download/<int:job_id>/', views.export_pdf_download, name='export_pdf_download'),
    path('terms/', views.terms_view, name='terms'),
    path('privacy/', views.privacy_view, name='privacy'),
    path('contact/', views.contact_view, name='contact'),
    path('sw.js', views.service_worker, name='service_worker'),
    path('submit-review-exclusive/', views.submit_review_view, name='submit_review'),
    path('revenue-report-exclusive/', views.revenue_report, name='revenue_report'),
    path('admin-dashboard-exclusive/', views.admin_dashboard, name='admin_dashboard'),
    
    # Management - Move more specific ones UP
    path('manage/affiliates/', views.manage_affiliates, name='manage_affiliates'),
    path('manage/blog/', include('blog.dashboard_urls')),
    path('manage/', views.manage_dashboard, name='manage_dashboard'),
    
    path('user-activity/', views.user_activity_report, name='user_activity_report'),
    path('affiliate/', views.affiliate_view, name='affiliate'),
    path('affiliate/join/', views.join_affiliate, name='join_affiliate'),
]
