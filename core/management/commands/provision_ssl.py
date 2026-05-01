"""
Management command to provision an SSL certificate for a custom domain.

Usage:
    python manage.py provision_ssl customdomain.com
    python manage.py provision_ssl --all   (provision all verified domains without certs)

This runs Certbot with the --nginx plugin so Nginx is automatically
updated with the new certificate.  Must be run as root (or via sudo)
on the production server.
"""

import subprocess
import logging

from django.core.management.base import BaseCommand, CommandError
from core.models import CustomDomain

logger = logging.getLogger('core')


class Command(BaseCommand):
    help = 'Provision SSL certificate for a custom domain via Certbot'

    def add_arguments(self, parser):
        parser.add_argument(
            'domain',
            nargs='?',
            help='The custom domain to provision SSL for',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Provision SSL for all active, verified domains',
        )

    def handle(self, *args, **options):
        if options['all']:
            domains = CustomDomain.objects.filter(
                is_active=True,
                dns_verified_at__isnull=False,
            ).values_list('domain', flat=True)

            if not domains:
                self.stdout.write(self.style.WARNING('No verified domains found.'))
                return

            for domain in domains:
                self._provision(domain)
        elif options['domain']:
            self._provision(options['domain'])
        else:
            raise CommandError('Provide a domain name or use --all')

    def _provision(self, domain):
        """Run certbot to get/renew an SSL certificate for the given domain."""
        self.stdout.write(f'Provisioning SSL for {domain}...')

        cmd = [
            'certbot', '--nginx',
            '-d', domain,
            '--non-interactive',
            '--agree-tos',
            '--email', 'admin@skillifly.cloud',
            '--redirect',           # auto-redirect HTTP → HTTPS
            '--keep-until-expiring', # don't re-issue if cert still valid
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS(
                    f'✓ SSL certificate active for {domain}'
                ))
                logger.info('SSL provisioned for %s', domain)
            else:
                self.stdout.write(self.style.ERROR(
                    f'✗ Certbot failed for {domain}: {result.stderr}'
                ))
                logger.error('SSL provisioning failed for %s: %s', domain, result.stderr)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(
                'certbot not found. Install with: sudo apt install certbot python3-certbot-nginx'
            ))
        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR(
                f'Certbot timed out for {domain}'
            ))
