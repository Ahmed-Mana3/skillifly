import hashlib
import os
from pathlib import Path

from celery import shared_task
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import PdfExportJob, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser


def _safe_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip("_-") or "portfolio"


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def generate_portfolio_pdf(self, job_id: int) -> str:
    """
    Generates a PDF for the given PdfExportJob and stores it in job.pdf_file.
    Uses Playwright Chromium printing for high-fidelity results.
    """
    job = PdfExportJob.objects.select_related("user").get(id=job_id)
    if job.status == PdfExportJob.Status.SUCCEEDED and job.pdf_file:
        return job.pdf_file.name

    job.status = PdfExportJob.Status.RUNNING
    job.error = ""
    job.save(update_fields=["status", "error", "updated_at"])

    try:
        user: CustomUser = job.user
        profile, _ = Profile.objects.get_or_create(user=user)
        personal_info = PersonalInfo.objects.filter(user=user).first()
        experiences = Experience.objects.filter(user=user)
        education = Education.objects.filter(user=user)
        skills = Skill.objects.filter(user=user)
        projects = Project.objects.filter(user=user)
        links = Link.objects.filter(user=user)

        html = render_to_string(
            "portfolios/common/portfolio_export_pdf.html",
            {
                "user_obj": user,
                "profile": profile,
                "personal_info": personal_info,
                "experiences": experiences,
                "education": education,
                "skills": skills,
                "projects": projects,
                "links": links,
                "generated_at": timezone.now(),
            },
        )

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            context = browser.new_context()
            page = context.new_page()
            
            # Use 'load' instead of 'networkidle' to be more robust against slow external fonts/scripts
            page.set_content(html, wait_until="load", timeout=30000)
            
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"},
                scale=1.0,
                display_header_footer=False,
            )
            browser.close()

        base = _safe_filename(user.username)
        digest = hashlib.sha256(job.source_hash.encode()).hexdigest()[:10]
        filename = f"{base}-{digest}.pdf"
        job.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)
        job.status = PdfExportJob.Status.SUCCEEDED
        job.error = ""
        job.save()
        return job.pdf_file.name
    except Exception as e:
        job.status = PdfExportJob.Status.FAILED
        job.error = str(e)
        job.save(update_fields=["status", "error", "updated_at"])
        raise

