import random

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.models import (
    School, SchoolStudent, Project, CustomUser, PersonalInfo,
    SchoolVideoRating, SchoolStudentRating, SchoolVideoComment,
)


STUDENTS = [
    ("Omar Mostafa", "Short-Form Editor", "#0B3954",
     "Third-year student at Serb Skool specializing in short-form and social video. Big on pacing, hooks, and clean sound design.", False),
    ("Laila Samir", "Motion Designer", "#6D28D9",
     "Motion designer obsessed with easing curves, kinetic type, and logo reveals that snap.", False),
    ("Ahmed Khaled", "Colorist", "#059669",
     "Colorist training in DaVinci Resolve. Day-to-night grades, skin tones, and filmic LUTs.", False),
    ("Nour El-Gendy", "Documentary Editor", "#DC2626",
     "Documentary editor who believes rhythm is emotion. Cuts long-form stories people feel.", False),
    ("Youssef Mansour", "Content Editor", "#334155",
     "Content editor turning 4-hour streams into watchable highlight packages.", False),
    ("Mariam Ghazal", "Social Media Editor", "#0EA5E9",
     "Social media editor who knows hooks, retention graphs, and platform-native formats.", False),
    ("Hassan Tarek", "Wedding Filmmaker", "#B45309",
     "Wedding filmmaker crafting emotional highlight films with cinematic sound design.", False),
    ("Salma Farouk", "Brand Video Editor", "#BE185D",
     "Brand video editor blending motion graphics and footage for commercial work.", False),
    ("Karim El-Sayed", "Music Video Editor", "#0E7490",
     "Music video editor fluent in beat-matching cuts and glitch transitions.", True),
    ("Hana Adel", "Podcast Editor", "#B91C1C",
     "Podcast editor squeezing dead air out of long conversations into tight, bingeable shows.", True),
    ("Mostafa Badr", "Gaming Editor", "#1D4ED8",
     "Gaming editor specializing in high-energy montages and meme cuts.", True),
    ("Rana Hassan", "Commercial Editor", "#0B3954",
     "Commercial editor with an eye for pacing that holds attention to the last frame.", True),
]

VIDEOS = [
    ("A Cinematic Travel Reel — Cairo in 60 Seconds", "cinematic-travel-reel", "Omar Mostafa", "2:41", 24000,
     "A 60-second cinematic travel reel shot and cut around Cairo — matched cuts, ambient sound design, and a pace that never drags."),
    ("Motion Design Breakdown — Logo Animation", "logo-animation", "Laila Samir", "3:12", 18000,
     "A frame-by-frame breakdown of a logo animation: easing curves, overshoot, and the details that make it feel alive."),
    ("Color Grading: Day to Night in DaVinci Resolve", "color-grading-day-to-night", "Ahmed Khaled", "4:05", 15000,
     "Grading a single shot from golden hour to night — tracking, matching, and grading skin tones under moonlight."),
    ("Interview Edit with Invisible Cuts", "invisible-cuts-interview", "Nour El-Gendy", "5:22", 21000,
     "A talking-head interview edited with invisible cuts — punch-ins, B-roll, and cutaway rhythm that keeps viewers watching."),
    ("Faceless YouTube Channel in a Weekend", "faceless-youtube-channel", "Youssef Mansour", "6:48", 33000,
     "Building a faceless YouTube channel from scratch — script hooks, stock footage assembly, and pacing for watchtime."),
    ("Reels Formula That Actually Gets Watchtime", "reels-formula", "Mariam Ghazal", "3:35", 28000,
     "The hook patterns, retention tricks, and format-native editing that make reels perform."),
]

SEED_COMMENTS = [
    ("Laila Samir", "#6D28D9", 5, "The pacing on this is unreal. Big fan!"),
    ("Ahmed Khaled", "#059669", 5, "Can you share the ease curve you used for the intro?"),
    ("Nour El-Gendy", "#DC2626", 5, "That skin-tone tracking tip just fixed my workflow."),
    ("Youssef Mansour", "#334155", 5, "Smooth cutaways. Saving this for reference."),
    ("Mariam Ghazal", "#0EA5E9", 5, "Straightforward and super actionable. Thanks!"),
    ("Hassan Tarek", "#B45309", 5, "Hook ideas alone are worth the watch."),
]


class Command(BaseCommand):
    help = "Seed the Serb Skool demo data (idempotent)."

    def handle(self, *args, **options):
        school, _ = School.objects.get_or_create(
            slug="serb-skool",
            defaults={
                "name": "Serb Skool",
                "tagline": "Where tomorrow's video editors learn the craft. Meet our students, watch their work, and leave a note.",
                "discount_code": "SERBSKOOL",
            },
        )

        students = {}
        for name, specialty, color, bio, hidden in STUDENTS:
            username = slugify(name).replace("-", "_")
            user, _ = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@serbskool.test",
                    "first_name": name.split()[0],
                    "last_name": " ".join(name.split()[1:]) or name.split()[0],
                },
            )
            PersonalInfo.objects.get_or_create(
                user=user,
                defaults={
                    "full_name": name,
                    "title": specialty,
                    "email": f"{username}@serbskool.test",
                    "phone": "+20 100 000 0000",
                    "bio": bio,
                },
            )
            student, created = SchoolStudent.objects.get_or_create(
                school=school,
                user=user,
                defaults={
                    "is_hidden": hidden,
                },
            )
            if not created:
                student.is_hidden = hidden
                student.save()
            students[name] = student

        # preserve original display order
        for i, (name, *_rest) in enumerate(STUDENTS):
            students[name].order = i
            students[name].save()

        for title, slug, student_name, duration, views, description in VIDEOS:
            student = students[student_name]
            video, created = Project.objects.get_or_create(
                user=student.user,
                slug=slug,
                defaults={
                    "title": title,
                    "details": description,
                },
            )
            if not created and (video.title != title or video.details != description):
                video.title = title
                video.details = description
                video.save()
            if not video.school_video_ratings.exists():
                for _ in range(random.randint(3, 6)):
                    SchoolVideoRating.objects.create(
                        project=video,
                        value=random.choice([4, 5, 5, 5]),
                    )

        all_projects = []
        for student in students.values():
            all_projects.extend(student.user.projects.all())
        for i, (author, color, stars, body) in enumerate(SEED_COMMENTS):
            if not all_projects:
                break
            project = all_projects[i % len(all_projects)]
            SchoolVideoComment.objects.get_or_create(
                project=project,
                author_name=author,
                body=body,
                defaults={"author_color": color, "stars": stars},
            )

        for student in students.values():
            if not student.ratings.exists():
                for _ in range(random.randint(3, 8)):
                    SchoolStudentRating.objects.create(
                        student=student,
                        value=random.choice([4, 5, 5, 5]),
                    )

        video_count = sum(s.user.projects.count() for s in students.values())
        self.stdout.write(self.style.SUCCESS(
            f"Seeded school '{school.name}' with {school.students.count()} students and {video_count} videos."
        ))
