"""
Set up a portfolio for someone who replied to a nudge with their video links.

Does exactly what the welcome page does (link lookup, thumbnail, default theme, personal
info from signup) but labels the projects ``source='concierge'`` so activation reports can
show hand-set-up portfolios separately from real product activation.

Usage:
    python manage.py add_concierge_projects sara https://youtu.be/abc12345678 https://vimeo.com/123456
    python manage.py add_concierge_projects sara <url> --title "Brand film" --lang ar
    python manage.py add_concierge_projects sara <url> --dry-run     # look the links up, create nothing
"""
from django.core.management.base import BaseCommand, CommandError
from django.http import QueryDict

from core import activation, oembed, onboarding
from core.models import CustomUser

MAX_PER_RUN = 20


class Command(BaseCommand):
    help = "Add projects to an editor's portfolio from video links, labelled as concierge-created."

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('urls', nargs='+', help='One or more video links.')
        parser.add_argument('--title', action='append', default=[],
                            help='Title for the matching link (repeat per link, in order). Default: from the lookup.')
        parser.add_argument('--lang', choices=['en', 'ar'], default='en', help='Language of the default title.')
        parser.add_argument('--dry-run', action='store_true', help='Look the links up and report; create nothing.')

    def handle(self, *args, **opts):
        user = CustomUser.objects.filter(username=opts['username']).first()
        if user is None:
            raise CommandError(f"No user named {opts['username']!r}.")
        if not user.is_active:
            raise CommandError(f'{user.username} has not verified their email yet.')
        if not activation.is_editor(user):
            raise CommandError(f'{user.username} is not an editor account.')

        urls = opts['urls'][:MAX_PER_RUN]
        if len(opts['urls']) > MAX_PER_RUN:
            self.stderr.write(f'Only the first {MAX_PER_RUN} links are used.')

        if opts['dry_run']:
            for url in urls:
                meta = oembed.fetch(url)
                state = 'ok' if meta.ok else f'error: {meta.error}'
                verdict = ' (would be refused)' if oembed.is_hard_failure(meta) else ''
                self.stdout.write(f'  {url} -> {state}{verdict} | {meta.provider} | {meta.video_type} | {meta.title!r}')
            self.stdout.write('Dry run: nothing created.')
            return

        data = QueryDict(mutable=True)
        data.setlist('url', urls)
        data.setlist('title', [*opts['title'], *[''] * (len(urls) - len(opts['title']))])
        data.setlist('video_type', [''] * len(urls))
        arabic = opts['lang'] == 'ar'

        created, errors = onboarding.create_projects_from_links(
            user, data, arabic=arabic, source='concierge', limit=MAX_PER_RUN,
        )
        if created:
            onboarding.ensure_default_theme(user)
            onboarding.ensure_personal_info(user, arabic=arabic)
        for project in created:
            self.stdout.write(self.style.SUCCESS(f'  added {project.title!r} ({project.video_type}) <- {project.url}'))
        for index, code in sorted(errors.items()):
            self.stdout.write(self.style.WARNING(
                f'  skipped {urls[index]}: {onboarding.error_message(code)}'
            ))
        skipped_dupes = len([u for u in urls if u.strip()]) - len(created) - len(errors)
        if skipped_dupes > 0:
            self.stdout.write(f'  {skipped_dupes} link(s) were already in the portfolio.')
        self.stdout.write(self.style.SUCCESS(
            f'Done: {len(created)} added to {user.username} (source=concierge).'
        ))
