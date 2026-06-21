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
]
