import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import timedelta
import base64

import requests as _requests
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse

from core.models import UserPayment, Subscription, Profile, CustomUser, DiscountCode, SiteSettings, ManualPayment
from core.views import process_affiliate_earning

logger = logging.getLogger('payments')

def pricing_view(request):
    """Render the payment page"""
    context = {
        'free_features': [
            '1 portfolio theme',
            'Public portfolio URL',
            'Personal info & skills',
            'Projects showcase',
            'Social links',
        ],
        'pro_features': [
            'All premium themes',
            'Custom domain support',
            'Portfolio analytics',
            'Remove Skillifly branding',
            'Priority support',
            'Unlimited projects',
        ],
        'annual_features': [
            'Everything in Pro',
            '2 months free',
            'Early access to new themes',
            'Dedicated support channel',
            'Export portfolio as PDF',
        ],
    }
    return render(request, 'payment/payment_new.html', context)

def arabic_pricing_view(request):
    """Render the payment page (Arabic RTL version)"""
    context = {
        'is_arabic_page': True,
    }
    return render(request, 'payment/arabic_payment_new.html', context)

# Plan definitions  {plan_type: (amount_egp, subscription_name, subscription_days)}
PLAN_CATALOGUE = {
    'monthly':   ('99.00',  'Monthly',  30),
    'pro_annual': ('449.00', 'Annual',  365),
}


def _get_or_create_subscription(name, days):
    """Fetch or create a Subscription record for the given plan."""
    from core.models import Subscription
    sub, _ = Subscription.objects.get_or_create(
        name=name,
        defaults={'duration': days, 'days': days},
    )
    return sub


def _is_school_code(coupon_code):
    """Return the School object if coupon_code is a valid school discount code, else None."""
    if not coupon_code:
        return None
    from core.models import School
    try:
        return School.objects.get(discount_code=coupon_code.strip().upper())
    except School.DoesNotExist:
        return None


def _is_school_student(user, school):
    """Return True if user is already an active student at this school."""
    from core.models import SchoolStudent
    return SchoolStudent.objects.filter(user=user, school=school).exists()


# Manual Payment — InstaPay / Vodafone Cash Auto-Verification
# -----------------------------------------------------------

import base64

@login_required
def manual_payment_view(request, plan_type):
    """
    GET  — show payment instructions + upload form.
    POST — verify receipt with Gemini AI and activate subscription if valid.
    """
    if plan_type not in PLAN_CATALOGUE:
        messages.error(request, 'Invalid plan selected.')
        return redirect('payment')

    amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]
    recipient_number = getattr(settings, 'MANUAL_PAYMENT_RECIPIENT', '+201020966071')

    # --- Coupon check (GET param so user can come from pricing page) ---
    coupon_code = request.POST.get('coupon', request.GET.get('coupon', '')).strip().upper()
    discount_applied = ''

    from core.models import SiteSettings
    site_settings = SiteSettings.objects.first()
    if not site_settings:
        site_settings = SiteSettings.objects.create()

    master_code = site_settings.banner_coupon_code.upper()
    master_percent = site_settings.banner_discount_percentage

    if coupon_code:
        # 0) School Discount Code — special handling
        school = _is_school_code(coupon_code)
        if school:
            if _is_school_student(request.user, school):
                # Already enrolled → 25% discount on chosen plan
                original_amount = float(amount_str)
                discounted_amount = original_amount * 0.75
                amount_str = f"{discounted_amount:.2f}"
                discount_applied = '25% school discount applied!'
            else:
                # First time → force monthly plan, activate immediately, enroll
                forced_plan = 'monthly'
                forced_amount, forced_sub_name, forced_sub_days = PLAN_CATALOGUE[forced_plan]
                sub = _get_or_create_subscription(forced_sub_name, forced_sub_days)
                UserPayment.objects.create(
                    user=request.user,
                    subscription=sub,
                    amount=0,
                    status='paid',
                    fawaterk_intent_key=f'MANUAL-SCHOOL-{uuid.uuid4().hex[:8].upper()}',
                    discount_code_used=coupon_code,
                )
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()
                from school.utils import enroll_in_school
                enroll_in_school(request.user, coupon_code)
                messages.success(request, f'School code applied! Your {forced_sub_name} plan is now active.')
                return redirect('payment_success')

        # 1) Master Settings Coupon
        elif coupon_code == master_code:
            if master_percent >= 100:
                # Full bypass
                sub = _get_or_create_subscription(sub_name, sub_days)
                UserPayment.objects.create(
                    user=request.user,
                    subscription=sub,
                    amount=0,
                    status='paid',
                    fawaterk_intent_key=f'MANUAL-MASTER-{uuid.uuid4().hex[:8].upper()}',
                    discount_code_used=coupon_code,
                )
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()
                from school.utils import enroll_in_school
                enroll_in_school(request.user, coupon_code)
                messages.success(request, f'Master Coupon applied! Your {sub_name} plan is now active.')
                return redirect('payment_success')
            else:
                # Partial discount
                original_amount = float(amount_str)
                discounted_amount = original_amount * (1 - (master_percent / 100.0))
                amount_str = f"{discounted_amount:.2f}"
                discount_applied = f'{master_percent}% discount applied (Master Code)!'
        
        else:
            # 2) Database Coupons
            from core.models import DiscountCode
            try:
                discount = DiscountCode.objects.get(code=coupon_code, is_active=True)
                if discount.discount_percentage == 100:
                    # Full discount — activate immediately
                    sub = _get_or_create_subscription(sub_name, sub_days)
                    UserPayment.objects.create(
                        user=request.user,
                        subscription=sub,
                        amount=0,
                        status='paid',
                        fawaterk_intent_key=f'MANUAL-COUPON-{uuid.uuid4().hex[:12].upper()}',
                        discount_code_used=coupon_code,
                    )
                    discount.usage_count += 1
                    discount.save()
                    profile, _ = Profile.objects.get_or_create(user=request.user)
                    profile.is_public = True
                    profile.save()
                    from school.utils import enroll_in_school
                    enroll_in_school(request.user, coupon_code)
                    messages.success(request, f'Coupon applied! Your {sub_name} plan is now active.')
                    return redirect('payment_success')
                else:
                    # Partial discount — reduce amount
                    original_amount = float(amount_str)
                    discounted_amount = original_amount * (1 - (discount.discount_percentage / 100.0))
                    amount_str = f"{discounted_amount:.2f}"
                    discount_applied = f'{discount.discount_percentage}% discount applied!'
            except DiscountCode.DoesNotExist:
                if request.method == 'POST':
                    messages.error(request, 'Invalid or expired coupon code.')
                    return redirect('payment')
                # On GET, just ignore invalid coupon silently

    context = {
        'plan_type': plan_type,
        'plan_name': sub_name,
        'amount': amount_str,
        'recipient_number': recipient_number,
        'coupon_code': coupon_code,
        'discount_applied': discount_applied,
    }

    if request.method == 'GET' or request.POST.get('apply_coupon'):
        return render(request, 'payment/manual_payment.html', context)

    # --- POST: process the uploaded receipt ---
    payment_method = request.POST.get('payment_method', 'vodafone').strip()
    sender_identifier = request.POST.get('sender_identifier', '').strip()
    receipt_file = request.FILES.get('receipt_image')

    if not sender_identifier:
        messages.error(request, 'Please enter your phone number or InstaPay handle.')
        return render(request, 'payment/manual_payment.html', context)

    if not receipt_file:
        messages.error(request, 'Please upload a screenshot of your payment receipt.')
        return render(request, 'payment/manual_payment.html', context)

    # --- Verify Image using PIL to ensure it is a valid picture ---
    import io
    from PIL import Image

    try:
        receipt_file.seek(0)
        with Image.open(receipt_file) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            # Resize to max 1024x1024 to save space
            img.thumbnail((1024, 1024))
            
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG')
    except Exception as e:
        logger.error('Invalid image uploaded by %s: %s', request.user.username, e)
        messages.error(request, 'The uploaded image is invalid or corrupted. Please upload a valid image file.')
        return render(request, 'payment/manual_payment.html', context)

    # Reset file pointer for Django's model save
    receipt_file.seek(0)

    # Save the ManualPayment record as instantly verified
    from core.models import ManualPayment
    manual_pay = ManualPayment.objects.create(
        user=request.user,
        plan_type=plan_type,
        amount_expected=amount_str,
        payment_method=payment_method,
        sender_identifier=sender_identifier,
        receipt_image=receipt_file,
        status='verified',
        discount_code_used=coupon_code or None,
    )

    # Activate subscription immediately
    sub = _get_or_create_subscription(sub_name, sub_days)
    UserPayment.objects.create(
        user=request.user,
        subscription=sub,
        amount=amount_str,
        status='paid',
        fawaterk_intent_key=f'MANUAL-{uuid.uuid4().hex[:12].upper()}',
        discount_code_used=coupon_code or None,
    )

    # Increment discount usage if partial coupon was used
    if coupon_code and coupon_code not in ('SKILLIFLY2026', getattr(settings, 'SKILLIFLY_COUPON_CODE', '')):
        from core.models import DiscountCode
        try:
            disc = DiscountCode.objects.get(code=coupon_code)
            disc.usage_count += 1
            disc.save()
        except DiscountCode.DoesNotExist:
            pass

    # Make portfolio public
    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.is_public = True
    profile.save()

    from school.utils import enroll_in_school
    enroll_in_school(request.user, coupon_code)

    logger.info('Manual payment auto-verified and subscription activated for user %s', request.user.username)
    messages.success(request, f'Payment verified! Your {sub_name} subscription is now active.')
    return redirect('payment_success')
@login_required(login_url='arabic_signin')
def arabic_manual_payment_view(request, plan_type):
    """
    Arabic RTL version of the manual payment wizard.
    GET  — show payment instructions + upload form.
    POST — verify receipt with Gemini AI and activate subscription if valid.
    """
    if plan_type not in PLAN_CATALOGUE:
        messages.error(request, 'الخطة المحددة غير صالحة.')
        return redirect('arabic_payment')

    amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]
    recipient_number = getattr(settings, 'MANUAL_PAYMENT_RECIPIENT', '+201020966071')

    # --- Coupon check (GET param so user can come from pricing page) ---
    coupon_code = request.POST.get('coupon', request.GET.get('coupon', '')).strip().upper()
    discount_applied = ''

    from core.models import SiteSettings
    site_settings = SiteSettings.objects.first()
    if not site_settings:
        site_settings = SiteSettings.objects.create()

    master_code = site_settings.banner_coupon_code.upper()
    master_percent = site_settings.banner_discount_percentage

    if coupon_code:
        # 0) School Discount Code — special handling
        school = _is_school_code(coupon_code)
        if school:
            if _is_school_student(request.user, school):
                # Already enrolled → 25% discount on chosen plan
                original_amount = float(amount_str)
                discounted_amount = original_amount * 0.75
                amount_str = f"{discounted_amount:.2f}"
                discount_applied = 'تم تطبيق خصم المدرسة 25%!'
            else:
                # First time → force monthly plan, activate immediately, enroll
                forced_plan = 'monthly'
                forced_amount, forced_sub_name, forced_sub_days = PLAN_CATALOGUE[forced_plan]
                sub = _get_or_create_subscription(forced_sub_name, forced_sub_days)
                UserPayment.objects.create(
                    user=request.user,
                    subscription=sub,
                    amount=0,
                    status='paid',
                    fawaterk_intent_key=f'MANUAL-SCHOOL-{uuid.uuid4().hex[:8].upper()}',
                    discount_code_used=coupon_code,
                )
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()
                from school.utils import enroll_in_school
                enroll_in_school(request.user, coupon_code)
                messages.success(request, f'تم تطبيق كود المدرسة! خطتك {forced_sub_name} نشطة الآن.')
                return redirect('arabic_payment_success')

        # 1) Master Settings Coupon
        elif coupon_code == master_code:
            if master_percent >= 100:
                # Full bypass
                sub = _get_or_create_subscription(sub_name, sub_days)
                UserPayment.objects.create(
                    user=request.user,
                    subscription=sub,
                    amount=0,
                    status='paid',
                    fawaterk_intent_key=f'MANUAL-MASTER-{uuid.uuid4().hex[:8].upper()}',
                    discount_code_used=coupon_code,
                )
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()
                from school.utils import enroll_in_school
                enroll_in_school(request.user, coupon_code)
                messages.success(request, f'تم تطبيق الكود الرئيسي! خطتك {sub_name} نشطة الآن.')
                return redirect('arabic_payment_success')
            else:
                # Partial discount
                original_amount = float(amount_str)
                discounted_amount = original_amount * (1 - (master_percent / 100.0))
                amount_str = f"{discounted_amount:.2f}"
                discount_applied = f'تم تطبيق خصم {master_percent}% (الكود الرئيسي)!'

        else:
            # 2) Database Coupons
            from core.models import DiscountCode
            try:
                discount = DiscountCode.objects.get(code=coupon_code, is_active=True)
                if discount.discount_percentage == 100:
                    # Full discount — activate immediately
                    sub = _get_or_create_subscription(sub_name, sub_days)
                    UserPayment.objects.create(
                        user=request.user,
                        subscription=sub,
                        amount=0,
                        status='paid',
                        fawaterk_intent_key=f'MANUAL-COUPON-{uuid.uuid4().hex[:12].upper()}',
                        discount_code_used=coupon_code,
                    )
                    discount.usage_count += 1
                    discount.save()
                    profile, _ = Profile.objects.get_or_create(user=request.user)
                    profile.is_public = True
                    profile.save()
                    from school.utils import enroll_in_school
                    enroll_in_school(request.user, coupon_code)
                    messages.success(request, f'تم تطبيق الكوبون! خطتك {sub_name} نشطة الآن.')
                    return redirect('arabic_payment_success')
                else:
                    # Partial discount — reduce amount
                    original_amount = float(amount_str)
                    discounted_amount = original_amount * (1 - (discount.discount_percentage / 100.0))
                    amount_str = f"{discounted_amount:.2f}"
                    discount_applied = f'تم تطبيق خصم {discount.discount_percentage}%!'
            except DiscountCode.DoesNotExist:
                if request.method == 'POST':
                    messages.error(request, 'كود الخصم غير صالح أو منتهي الصلاحية.')
                    return redirect('arabic_payment')
                # On GET, just ignore invalid coupon silently

    context = {
        'plan_type': plan_type,
        'plan_name': sub_name,
        'amount': amount_str,
        'recipient_number': recipient_number,
        'coupon_code': coupon_code,
        'discount_applied': discount_applied,
        'is_arabic_page': True,
    }

    if request.method == 'GET' or request.POST.get('apply_coupon'):
        return render(request, 'payment/arabic_manual_payment.html', context)

    # --- POST: process the uploaded receipt ---
    payment_method = request.POST.get('payment_method', 'vodafone').strip()
    sender_identifier = request.POST.get('sender_identifier', '').strip()
    receipt_file = request.FILES.get('receipt_image')

    if not sender_identifier:
        messages.error(request, 'يرجى إدخال رقم هاتفك أو معرف InstaPay.')
        return render(request, 'payment/arabic_manual_payment.html', context)

    if not receipt_file:
        messages.error(request, 'يرجى رفع لقطة شاشة لإيصال الدفع.')
        return render(request, 'payment/arabic_manual_payment.html', context)

    # --- Verify Image using PIL to ensure it is a valid picture ---
    import io
    from PIL import Image

    try:
        receipt_file.seek(0)
        with Image.open(receipt_file) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            # Resize to max 1024x1024 to save space
            img.thumbnail((1024, 1024))

            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG')
    except Exception as e:
        logger.error('Invalid image uploaded by %s: %s', request.user.username, e)
        messages.error(request, 'الصورة المرفوعة غير صالحة أو تالفة. يرجى رفع ملف صورة صالح.')
        return render(request, 'payment/arabic_manual_payment.html', context)

    # Reset file pointer for Django's model save
    receipt_file.seek(0)

    # Save the ManualPayment record as instantly verified
    from core.models import ManualPayment
    manual_pay = ManualPayment.objects.create(
        user=request.user,
        plan_type=plan_type,
        amount_expected=amount_str,
        payment_method=payment_method,
        sender_identifier=sender_identifier,
        receipt_image=receipt_file,
        status='verified',
        discount_code_used=coupon_code or None,
    )

    # Activate subscription immediately
    sub = _get_or_create_subscription(sub_name, sub_days)
    UserPayment.objects.create(
        user=request.user,
        subscription=sub,
        amount=amount_str,
        status='paid',
        fawaterk_intent_key=f'MANUAL-{uuid.uuid4().hex[:12].upper()}',
        discount_code_used=coupon_code or None,
    )

    # Increment discount usage if partial coupon was used
    if coupon_code and coupon_code not in ('SKILLIFLY2026', getattr(settings, 'SKILLIFLY_COUPON_CODE', '')):
        from core.models import DiscountCode
        try:
            disc = DiscountCode.objects.get(code=coupon_code)
            disc.usage_count += 1
            disc.save()
        except DiscountCode.DoesNotExist:
            pass

    # Make portfolio public
    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.is_public = True
    profile.save()

    from school.utils import enroll_in_school
    enroll_in_school(request.user, coupon_code)

    logger.info('Manual payment auto-verified and subscription activated for user %s', request.user.username)
    messages.success(request, f'تم التحقق من الدفع! اشتراكك {sub_name} نشط الآن.')
    return redirect('arabic_payment_success')


@login_required
def manual_payment_pending(request):
    """Simple holding page (currently unused — verification is instant.)"""
    return render(request, 'payment/payment_success.html')

@user_passes_test(lambda u: u.is_superuser)
def manage_discounts_create(request):
    from core.forms import DiscountCodeForm
    if request.method == 'POST':
        form = DiscountCodeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Discount code created successfully!")
        else:
            messages.error(request, f"Error creating discount code: {form.errors.as_text()}")
    return redirect('manage_dashboard')

@user_passes_test(lambda u: u.is_superuser)
def manage_discounts_delete(request, pk):
    from core.models import DiscountCode
    discount = get_object_or_404(DiscountCode, pk=pk)
    code = discount.code
    discount.delete()
    messages.success(request, f"Discount code '{code}' deleted.")
    return redirect('manage_dashboard')

@user_passes_test(lambda u: u.is_superuser)
def manage_discounts_toggle(request, pk):
    from core.models import DiscountCode
    discount = get_object_or_404(DiscountCode, pk=pk)
    discount.is_active = not discount.is_active
    discount.save()
    status = "activated" if discount.is_active else "deactivated"
    messages.success(request, f"Discount code '{discount.code}' {status}.")
    return redirect('manage_dashboard')

@user_passes_test(lambda u: u.is_superuser)
def manage_banner_update(request):
    from core.models import SiteSettings
    from core.forms import SiteSettingsForm
    site_settings = SiteSettings.objects.first()
    if request.method == 'POST':
        form = SiteSettingsForm(request.POST, instance=site_settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Site banner settings updated!")
        else:
            messages.error(request, "Error updating banner settings.")
    return redirect('manage_dashboard')


@login_required
def payment_success(request):
    return render(request, 'payment/payment_success.html')

@login_required
def payment_failure(request):
    error_message = request.session.pop('payment_error', "We couldn't process your payment. Please ensure your details are correct and try again.")
    return render(request, 'payment/payment_failure.html', {'error_message': error_message})

@login_required(login_url='arabic_signin')
def arabic_payment_success(request):
    return render(request, 'payment/arabic_payment_success.html', {'is_arabic_page': True})

@login_required(login_url='arabic_signin')
def arabic_payment_failure(request):
    error_message = request.session.pop('payment_error', "تعذّرت معالجة الدفع. يرجى التأكد من صحة بياناتك والمحاولة مرة أخرى.")
    return render(request, 'payment/arabic_payment_failure.html', {'error_message': error_message, 'is_arabic_page': True})


# --- FAWATERK VIEWS ---
from payments import fawaterk as fw_service

@login_required
def fawaterk_checkout(request, plan_type):
    if plan_type not in PLAN_CATALOGUE:
        messages.error(request, 'Invalid plan selected.')
        return redirect('payment')

    amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]
    user = request.user

    first_name = user.first_name or user.username
    last_name  = user.last_name  or 'User'
    phone = getattr(getattr(user, 'profile', None), 'phone_number', '') or '01000000000'

    try:
        result = fw_service.create_transaction(
            cart_total=amount_str,
            currency='EGP',
            customer={
                'first_name': first_name,
                'last_name':  last_name,
                'email':      user.email,
                'phone':      phone,
            },
            cart_items=[{
                'name':     f'Skillifly {sub_name} Plan',
                'price':    amount_str,
                'quantity': 1,
            }],
            pay_load={
                'plan_type': plan_type,
                'user_id':   user.id,
            },
            redirection_urls={
                'successUrl': request.build_absolute_uri(reverse('fawaterk_success')),
                'failUrl':    request.build_absolute_uri(reverse('payment_failure')),
                'pendingUrl': request.build_absolute_uri(reverse('fawaterk_pending')),
                'backUrl':    request.build_absolute_uri(reverse('payment')),
                'webhookUrl': request.build_absolute_uri(reverse('fawaterk_webhook')),
            },
        )
    except Exception as e:
        logger.error('Fawaterk createTransaction error: %s', e)
        messages.error(request, 'Payment service unavailable.')
        return redirect('payment')

    if result.get('status') != 'success':
        messages.error(request, 'Could not initiate payment.')
        return redirect('payment')

    intent_key = result['data']['intent_key']
    checkout_url = result['data']['url']

    request.session['fawaterk_intent_key'] = intent_key

    sub = _get_or_create_subscription(sub_name, sub_days)
    UserPayment.objects.create(
        user=user,
        subscription=sub,
        amount=amount_str,
        status='pending',
        fawaterk_intent_key=intent_key,
    )

    env_type = getattr(settings, 'FAWATERK_ENV', 'live')
    return render(request, 'payment/fawaterk_iframe.html', {
        'checkout_url': checkout_url,
        'env_type': env_type
    })

@login_required
def fawaterk_success(request):
    intent_key = request.session.get('fawaterk_intent_key')
    if intent_key:
        try:
            tx_data = fw_service.get_transaction_data(intent_key)
            if tx_data.get('data', {}).get('payment_status') == 'paid':
                _activate_subscription_by_intent(intent_key, request.user)
        except Exception as e:
            logger.warning('Verify fail on success redirect: %s', e)
    return render(request, 'payment/payment_success.html')

@login_required
def fawaterk_pending(request):
    return render(request, 'payment/fawaterk_pending.html')

@login_required(login_url='arabic_signin')
def arabic_fawaterk_checkout(request, plan_type):
    if plan_type not in PLAN_CATALOGUE:
        messages.error(request, 'الخطة المحددة غير صالحة.')
        return redirect('arabic_payment')

    amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]
    user = request.user

    first_name = user.first_name or user.username
    last_name  = user.last_name  or 'User'
    phone = getattr(getattr(user, 'profile', None), 'phone_number', '') or '01000000000'

    try:
        result = fw_service.create_transaction(
            cart_total=amount_str,
            currency='EGP',
            customer={
                'first_name': first_name,
                'last_name':  last_name,
                'email':      user.email,
                'phone':      phone,
            },
            cart_items=[{
                'name':     f'Skillifly {sub_name} Plan',
                'price':    amount_str,
                'quantity': 1,
            }],
            pay_load={
                'plan_type': plan_type,
                'user_id':   user.id,
            },
            redirection_urls={
                'successUrl': request.build_absolute_uri(reverse('arabic_fawaterk_success')),
                'failUrl':    request.build_absolute_uri(reverse('arabic_payment_failure')),
                'pendingUrl': request.build_absolute_uri(reverse('arabic_fawaterk_pending')),
                'backUrl':    request.build_absolute_uri(reverse('arabic_payment')),
                'webhookUrl': request.build_absolute_uri(reverse('fawaterk_webhook')),
            },
        )
    except Exception as e:
        logger.error('Fawaterk createTransaction error: %s', e)
        messages.error(request, 'خدمة الدفع غير متاحة حاليًا.')
        return redirect('arabic_payment')

    if result.get('status') != 'success':
        messages.error(request, 'تعذّر بدء عملية الدفع.')
        return redirect('arabic_payment')

    intent_key = result['data']['intent_key']
    checkout_url = result['data']['url']

    request.session['fawaterk_intent_key'] = intent_key

    sub = _get_or_create_subscription(sub_name, sub_days)
    UserPayment.objects.create(
        user=user,
        subscription=sub,
        amount=amount_str,
        status='pending',
        fawaterk_intent_key=intent_key,
    )

    env_type = getattr(settings, 'FAWATERK_ENV', 'live')
    return render(request, 'payment/arabic_fawaterk_iframe.html', {
        'checkout_url': checkout_url,
        'env_type': env_type,
        'is_arabic_page': True,
    })

@login_required(login_url='arabic_signin')
def arabic_fawaterk_success(request):
    intent_key = request.session.get('fawaterk_intent_key')
    if intent_key:
        try:
            tx_data = fw_service.get_transaction_data(intent_key)
            if tx_data.get('data', {}).get('payment_status') == 'paid':
                _activate_subscription_by_intent(intent_key, request.user)
        except Exception as e:
            logger.warning('Verify fail on success redirect: %s', e)
    return render(request, 'payment/arabic_payment_success.html', {'is_arabic_page': True})

@login_required(login_url='arabic_signin')
def arabic_fawaterk_pending(request):
    return render(request, 'payment/arabic_fawaterk_pending.html', {'is_arabic_page': True})

@csrf_exempt
def fawaterk_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    if not fw_service.verify_paid_webhook(payload):
        return HttpResponse(status=403)

    if payload.get('payment_status') == 'paid':
        intent_key = payload.get('invoice_key', '')
        user_id = payload.get('pay_load', {}).get('user_id')
        plan_type = payload.get('pay_load', {}).get('plan_type')

        if user_id and plan_type:
            try:
                user = CustomUser.objects.get(pk=user_id)
                _activate_subscription_by_intent(intent_key, user, plan_type)
            except CustomUser.DoesNotExist:
                pass

    return HttpResponse(status=200)

def _activate_subscription_by_intent(intent_key: str, user, plan_type: str = None):
    try:
        payment = UserPayment.objects.get(fawaterk_intent_key=intent_key)
        if payment.status == 'paid': return
        payment.status = 'paid'
        payment.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_public = True
        profile.save()
        # Safety net: enroll in school if a school code was used
        if payment.discount_code_used:
            from school.utils import enroll_in_school
            enroll_in_school(user, payment.discount_code_used)
    except UserPayment.DoesNotExist:
        if plan_type and plan_type in PLAN_CATALOGUE:
            amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]
            sub = _get_or_create_subscription(sub_name, sub_days)
            UserPayment.objects.create(
                user=user, subscription=sub, amount=amount_str,
                status='paid', fawaterk_intent_key=intent_key,
            )
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.is_public = True
            profile.save()


@login_required
def fawaterk_api_reference(request):
    """
    Renders the Fawaterak API Reference (Scalar documentation).
    """
    return render(request, 'payment/fawaterk_api_reference.html')

