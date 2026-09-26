"""
Release storage quota held by uploads that were never finished.

Creating an upload reserves space against the user's allowance. If the browser
is closed mid-upload — or the user never returns to the page — the row stays
'pending' forever and the space is never given back.

This command deletes such rows and asks Cloudflare to drop the media, so the
bytes are not kept or billed for either.

Safe to run repeatedly. Intended to be invoked periodically (cron / systemd
timer); it does nothing when there is nothing to clean up.

Usage:
    python manage.py reap_abandoned_uploads                  # older than 6 hours
    python manage.py reap_abandoned_uploads --hours 1 --dry-run
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core import cloudflare_stream
from core.models import Video

# Only unfinished uploads are reaped. A 'ready' video is content the user may
# have published, and an 'error' row is already excluded from quota accounting.
REAPABLE = ('pending', 'processing')


class Command(BaseCommand):
    help = 'Delete abandoned video uploads and release the storage they reserved'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=6,
            help='Only reap uploads untouched for this many hours (default: 6).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be deleted without deleting anything.',
        )

    def handle(self, *args, **options):
        hours = options['hours']
        if hours <= 0:
            self.stderr.write('--hours must be positive')
            return

        cutoff = timezone.now() - timedelta(hours=hours)
        stale = Video.objects.filter(
            status__in=REAPABLE, created_at__lt=cutoff
        ).order_by('created_at')

        count = stale.count()
        if not count:
            self.stdout.write(self.style.SUCCESS(
                f'No abandoned uploads older than {hours}h.'
            ))
            return

        verb = 'Would delete' if options['dry_run'] else 'Deleting'
        self.stdout.write(f'{verb} {count} abandoned upload(s) older than {hours}h:')

        freed = 0
        provider_failures = 0
        for video in stale:
            label = f'  {video.cloudflare_uid or "(no uid)"}  {video.size_bytes} bytes  {video.user_id}'
            if options['dry_run']:
                self.stdout.write(label)
                continue

            uid = video.cloudflare_uid
            video.delete()
            freed += 1

            if uid and cloudflare_stream.is_configured():
                try:
                    if not cloudflare_stream.delete_video(uid):
                        provider_failures += 1
                except cloudflare_stream.CloudflareStreamError:
                    provider_failures += 1
            self.stdout.write(self.style.SUCCESS(label))

        if options['dry_run']:
            return

        summary = f'Released {freed} upload(s).'
        if provider_failures:
            summary += (
                f' {provider_failures} could not be removed from Cloudflare and may'
                ' still be stored there.'
            )
        self.stdout.write(self.style.SUCCESS(summary))
