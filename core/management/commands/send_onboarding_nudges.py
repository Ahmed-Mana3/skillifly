"""
Send onboarding nudge emails to editors who stalled.

Intended to run hourly from a systemd timer (see ONBOARDING_V2_PLAN.md §7.5).
Each user receives at most one email per run, and each nudge at most once ever.
Does nothing unless "Nudges enabled" is ticked in Site Settings (dry runs excepted).

Usage:
    python manage.py send_onboarding_nudges                  # normal hourly run
    python manage.py send_onboarding_nudges --dry-run        # show who would get what
    python manage.py send_onboarding_nudges --only no_project_1h --limit 20
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import nudges, onboarding
from core.models import Project, UserPayment


class Command(BaseCommand):
    help = 'Send onboarding nudge emails to editors who have not finished their portfolio.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be sent; send nothing and write nothing.')
        parser.add_argument('--limit', type=int, default=50, help='Maximum emails per run (default 50).')
        parser.add_argument('--only', choices=nudges.KEYS, help='Only send this nudge.')
        parser.add_argument('--ignore-quiet-hours', action='store_true',
                            help='Send even between 22:00 and 09:00 Cairo time.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        if not dry and not onboarding.nudges_enabled():
            self.stdout.write('Nudges are disabled in Site Settings; nothing sent.')
            return
        if not opts['ignore_quiet_hours'] and nudges.in_quiet_hours():
            self.stdout.write('Quiet hours (22:00-09:00 Cairo); nothing sent.')
            return

        now = timezone.now()
        sent = skipped = 0
        for user in nudges.eligible_users(now).order_by('date_joined'):
            if sent >= opts['limit']:
                break
            n = Project.objects.filter(user=user).count()
            paid = UserPayment.objects.filter(user=user, status='paid').exists()
            key = nudges.due_key(user, now, project_count=n, has_paid=paid)
            if key is None or (opts['only'] and key != opts['only']):
                continue
            if dry:
                self.stdout.write(f'  would send {key} -> {user.email}')
                sent += 1
                continue
            if nudges.send_nudge(user, key, project_count=n):
                self.stdout.write(self.style.SUCCESS(f'  sent {key} -> {user.email}'))
                sent += 1
            else:
                skipped += 1

        verb = 'Would send' if dry else 'Sent'
        summary = f'{verb} {sent} nudge(s).'
        if skipped:
            summary += f' {skipped} failed or already sent.'
        self.stdout.write(self.style.SUCCESS(summary))
