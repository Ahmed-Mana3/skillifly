from django.urls import path
from . import views

urlpatterns = [
    path('', views.builder_view, name='builder'),
    path('update/', views.update_portfolio_view, name='update_portfolio'),
    path('ajax/save-category/', views.ajax_save_category, name='ajax_save_category'),
    path('ajax/delete-category/', views.ajax_delete_category, name='ajax_delete_category'),
    path('ajax/save-section-layout/', views.ajax_save_section_layout, name='ajax_save_section_layout'),
]
