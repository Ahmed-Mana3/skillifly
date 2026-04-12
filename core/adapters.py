from __future__ import annotations

from allauth.account.utils import user_email
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from allauth.utils import get_user_model


User = get_user_model()


class SkilliflySocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    - Auto-fill first_name/last_name from Google profile data.
    - Link social login to an existing local user with the same email (prevents duplicates).
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

