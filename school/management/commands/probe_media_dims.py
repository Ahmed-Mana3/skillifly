import re
import sys

from django.core.management.base import BaseCommand

from core.models import Project
from school.views import _mp4_dims_from_drive, _drive_stream_url


class Command(BaseCommand):
    help = "Probe real video dimensions for Drive-hosted reel/long projects and cache them on the Project."

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-probe projects that already have dims')

    def handle(self, *args, **options):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        force = options['force']
        qs = Project.objects.exclude(url__isnull=True).exclude(url='')
        drive = [p for p in qs if re.search(r'drive\.google\.com', p.url or '')]
        done = 0
        for p in drive:
            if p.media_width and p.media_height and not force:
                continue
            if not _drive_stream_url(p.url):
                continue
            dims = _mp4_dims_from_drive(p.url)
            if dims:
                Project.objects.filter(pk=p.pk).update(media_width=dims[0], media_height=dims[1])
                ratio = 'portrait' if dims[0] < dims[1] else 'landscape' if dims[0] > dims[1] else 'square'
                self.stdout.write(f'  #{p.pk} {p.title[:50]:<52} {dims[0]}x{dims[1]} {ratio}')
                done += 1
            else:
                self.stdout.write(f'  #{p.pk} {p.title[:50]:<52} (no dims / not streamable)')
            self.stdout.flush()
        self.stdout.write(self.style.SUCCESS(f'Probed {done} Drive video(s).'))
