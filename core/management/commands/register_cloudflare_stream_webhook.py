"""
Register the Cloudflare Stream webhook so Django is told when a video
finishes processing.

One-time setup. Cloudflare answers with a signing secret — print it and put
it in your environment as CLOUDFLARE_STREAM_WEBHOOK_SECRET. Without it the
webhook endpoint rejects every request, and the upload page falls back to
polling.

Usage:
    python manage.py register_cloudflare_stream_webhook --url https://skillifly.cloud/videos/webhooks/cloudflare-stream/
    python manage.py register_cloudflare_stream_webhook --show     (inspect only)
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from core import cloudflare_stream


class Command(BaseCommand):
    help = 'Register the Cloudflare Stream webhook and print its signing secret'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            dest='url',
            default='',
            help='Public notification URL. Defaults to the webhook path on this site.',
        )
        parser.add_argument(
            '--show',
            action='store_true',
            help='Print the current registration without changing it.',
        )

    def handle(self, *args, **options):
        if not cloudflare_stream.is_configured():
            raise CommandError(
                'CLOUDFLARE_STREAM_API_TOKEN is not set. Add it to your environment first.'
            )

        if options['show']:
            self.stdout.write(self.style.MIGRATE_HEADING('Cloudflare Stream webhook'))
            self.stdout.write(
                f'  notification path : {reverse("cloudflare_stream_webhook")}'
                '\n  public url        : https://<your-domain>'
                f'{reverse("cloudflare_stream_webhook")}'
            )
            self.stdout.write(
                '  secret configured : '
                + ('yes' if settings.CLOUDFLARE_STREAM_WEBHOOK_SECRET else 'no')
            )
            return

        notification_url = (options['url'] or '').strip()
        if not notification_url:
            raise CommandError(
                'Pass the public notification URL, for example:\n'
                '  python manage.py register_cloudflare_stream_webhook '
                '--url https://skillifly.cloud/videos/webhooks/cloudflare-stream/'
            )
        if not notification_url.startswith('https://'):
            # Cloudflare will not deliver to plain http in production.
            self.stdout.write(self.style.WARNING(
                f'  note: {notification_url} is not https. Cloudflare may refuse to deliver.'
            ))

        try:
            result = cloudflare_stream.register_webhook(notification_url)
        except cloudflare_stream.CloudflareStreamError as exc:
            raise CommandError(str(exc))

        secret = (result.get('result') or {}).get('secret', '')

        self.stdout.write(self.style.SUCCESS('Webhook registered.'))
        self.stdout.write(f'  notification url : {notification_url}')
        if secret:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Save this secret — Cloudflare shows it only once:'))
            self.stdout.write(f'  CLOUDFLARE_STREAM_WEBHOOK_SECRET={secret}')
            self.stdout.write('')
            self.stdout.write('Add it to your .env (or systemd environment) and restart the app.')
        else:
            self.stdout.write(self.style.WARNING(
                'Cloudflare did not return a secret. If a webhook was already registered, '
                'delete it in the dashboard first so a new secret is issued.'
            ))
