from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.utils import user_email
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from allauth.utils import get_user_model
from core.models import UserAccount


User = get_user_model()


class SkillliflyAccountAdapter(DefaultAccountAdapter):
    """
    Override the post-password-change redirect to send users back to their profile page.
    """

    def get_password_change_redirect_url(self, request):
        if request.GET.get("next", "").startswith("/ar/"):
            return "/ar/profile/"
        return "/profile/"

    def send_password_reset_mail(self, user, email, context):
        """
        Track when a password reset is requested from an Arabic page so the
        follow-up reset pages (done / from-key / done) render in Arabic too.
        """
        request = context.get("request")
        if request is not None:
            next_target = request.GET.get("next") or request.POST.get("next") or ""
            is_arabic = (
                request.path.startswith("/ar/")
                or next_target.startswith("/ar/")
                or request.session.get("is_arabic_reset_flow", False)
            )
            if is_arabic:
                request.session["is_arabic_reset_flow"] = True
                context["is_arabic_page"] = True
        return super().send_password_reset_mail(user, email, context)


class SkilliflySocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    - Auto-fill first_name/last_name from Google profile data.
    - Link social login to an existing local user with the same email (prevents duplicates).
    - Record the account type chosen on the signup funnel in the UserAccount table,
      and auto-complete signup for clients (they never see the username step).
    """

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        extra = (sociallogin.account.extra_data or {}) if getattr(sociallogin, "account", None) else {}

        given_name = (extra.get("given_name") or data.get("first_name") or "").strip()
        family_name = (extra.get("family_name") or data.get("last_name") or "").strip()

        # Only fill if empty (never overwrite user edits)
        if given_name and not (user.first_name or "").strip():
            user.first_name = given_name
        if family_name and not (user.last_name or "").strip():
            user.last_name = family_name

        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        # Persist the account type chosen on the signup funnel. Runs for both the
        # auto-signup (client) and username-form (editor) completion paths.
        account_type = request.session.get("signup_account_type", "editor")
        if account_type in ("editor", "client"):
            UserAccount.objects.update_or_create(user=user, defaults={"account_type": account_type})
        elif account_type == "school_admin":
            # School admin: create account without school (school is chosen on a separate page)
            UserAccount.objects.update_or_create(user=user, defaults={"account_type": "school_admin"})
        request.session.pop("signup_account_type", None)
        return user

    def is_auto_signup_allowed(self, request, sociallogin):
        # Clients sign up with a single Google click — skip the username picker.
        # School admins need to pick a school on a separate page, so also skip here.
        # The session flag is intentionally left in place so save_user can read it.
        at = request.session.get("signup_account_type")
        if at in ("client", "school_admin"):
            return True
        return super().is_auto_signup_allowed(request, sociallogin)

    def pre_social_login(self, request, sociallogin):
        """
        If a user already exists with the same email, connect this social login to that user.
        """
        # Already linked
        if sociallogin.is_existing:
            return

        email = (user_email(sociallogin.user) or "").strip().lower()
        if not email:
            return

        try:
            existing_user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        # Prevent connecting if this social account is already associated elsewhere.
        if SocialAccount.objects.filter(provider=sociallogin.account.provider, uid=sociallogin.account.uid).exists():
            return

        sociallogin.connect(request, existing_user)

