from django.urls import path
from payments import views

urlpatterns = [
    path('payment/', views.pricing_view, name='payment'),
    path('manual-pay/<str:plan_type>/', views.manual_payment_view, name='manual_payment'),
    path('manual-pay/pending/', views.manual_payment_pending, name='manual_payment_pending'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/failure/', views.payment_failure, name='payment_failure'),
    path('manage/discounts/create/', views.manage_discounts_create, name='manage_discounts_create'),
    path('manage/discounts/delete/<int:pk>/', views.manage_discounts_delete, name='manage_discounts_delete'),
    path('manage/discounts/toggle/<int:pk>/', views.manage_discounts_toggle, name='manage_discounts_toggle'),
    path('manage/banner/update/', views.manage_banner_update, name='manage_banner_update'),
    path('fawaterk/checkout/<str:plan_type>/', views.fawaterk_checkout, name='fawaterk_checkout'),
    path('fawaterk/success/', views.fawaterk_success, name='fawaterk_success'),
    path('fawaterk/pending/', views.fawaterk_pending, name='fawaterk_pending'),
    path('fawaterk/api-reference/', views.fawaterk_api_reference, name='fawaterk_api_reference'),
    path('webhooks/fawaterak_json/', views.fawaterk_webhook, name='fawaterk_webhook'),
]
