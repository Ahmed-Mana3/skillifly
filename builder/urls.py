from django.urls import path
from . import api, views

urlpatterns = [
    # Per-item save API (autosave). "personal" comes before the <kind> routes.
    path('api/personal/', api.save_personal, name='builder_api_personal'),
    path('api/<slug:kind>/', api.create_item, name='builder_api_create'),
    path('api/<slug:kind>/<int:pk>/', api.update_item, name='builder_api_update'),
    path('api/<slug:kind>/<int:pk>/delete/', api.delete_item, name='builder_api_delete'),

    path('', views.builder_view, name='builder'),
    path('update/', views.update_portfolio_view, name='update_portfolio'),
    path('ajax/save-category/', views.ajax_save_category, name='ajax_save_category'),
    path('ajax/delete-category/', views.ajax_delete_category, name='ajax_delete_category'),
    path('ajax/save-section-layout/', views.ajax_save_section_layout, name='ajax_save_section_layout'),
    path('ajax/save-section-names/', views.ajax_save_section_names, name='ajax_save_section_names'),
]
