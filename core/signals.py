from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from core import activation
from core.models import Project


def _provider_of(url):
    """Best-effort provider label for a project link (analytics only)."""
    url = (url or '').lower()
    for needle, label in (
        ('youtu', 'youtube'), ('vimeo', 'vimeo'), ('tiktok', 'tiktok'),
        ('instagram', 'instagram'), ('drive.google', 'drive'),
        ('facebook', 'facebook'), ('fb.watch', 'facebook'),
        ('cloudflarestream', 'upload'),
    ):
        if needle in url:
            return label
    return 'other' if url else 'none'


@receiver(post_save, sender=Project, dispatch_uid='activation_project_created')
def project_created(sender, instance, created, raw=False, **kwargs):
    """Record `project_created` for every new Project, whichever code path made it."""
    if not created or raw:
        return
    src = activation.current_source()  # captured now; on_commit runs later
    user = instance.user
    url = instance.url or ''

    def _record():
        from core.models import Project as ProjectModel
        activation.track(
            user, 'project_created',
            source=src,
            nth=ProjectModel.objects.filter(user=user).count(),
            provider=_provider_of(url),
            seconds_since_signup=activation.seconds_since_signup(user),
        )

    # Only count projects that actually committed.
    transaction.on_commit(_record)
