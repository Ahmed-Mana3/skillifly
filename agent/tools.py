"""
Tool registry and execution engine for the Skillifly AI Agent.

All tool functions strictly enforce user isolation (user=request.user),
execute inside database transactions, and snapshot prior state for instant undo.
"""

from datetime import date, datetime
import re
from django.db import transaction
from django.shortcuts import get_object_or_404
from core.models import (
    CustomUser,
    Profile,
    PersonalInfo,
    Experience,
    Education,
    Skill,
    Project,
    ProjectCategory,
    Link,
    Creator,
    Theme,
    ClientReview,
    CustomDomain,
    UserPayment,
    PortfolioSnapshot,
)


def get_portfolio_state(user):
    """
    Serializes the complete current portfolio state for a given user.
    Used for LLM context injection and snapshot/undo mechanics.
    """
    profile = Profile.objects.filter(user=user).first()
    personal_info = PersonalInfo.objects.filter(user=user).first()
    
    theme_info = None
    if profile and profile.theme:
        theme_info = {
            "id": profile.theme.id,
            "name": profile.theme.name,
            "category": profile.theme.category.name if profile.theme.category else "General",
        }

    skills = list(Skill.objects.filter(user=user).values_list("name", flat=True))

    projects = []
    for p in Project.objects.filter(user=user).select_related("category"):
        projects.append({
            "id": p.id,
            "title": p.title,
            "url": p.url or "",
            "video_type": p.video_type,
            "category": p.category.name if p.category else "",
            "category_id": p.category_id,
            "details": p.details or "",
        })

    experiences = []
    for e in Experience.objects.filter(user=user):
        experiences.append({
            "id": e.id,
            "title": e.title,
            "company": e.company,
            "start_date": e.start_date.strftime("%Y-%m") if e.start_date else "",
            "end_date": e.end_date.strftime("%Y-%m") if e.end_date else "",
            "still_working": e.still_working,
            "details": e.details or "",
        })

    educations = []
    for ed in Education.objects.filter(user=user):
        educations.append({
            "id": ed.id,
            "school": ed.school,
            "degree": ed.degree,
            "field": ed.field,
            "year": ed.grade_year.year if ed.grade_year else None,
        })

    links = []
    for l in Link.objects.filter(user=user):
        links.append({
            "id": l.id,
            "platform": l.platform,
            "url": l.url,
        })

    categories = list(ProjectCategory.objects.filter(user=user).values("id", "name"))

    reviews = []
    for rev in ClientReview.objects.filter(user=user):
        reviews.append({
            "id": rev.id,
            "user_name": rev.user_name,
            "user_title": rev.user_title or "",
            "content": rev.content,
            "rating": rev.rating,
            "is_featured": rev.is_featured,
        })

    creators = []
    for c in Creator.objects.filter(user=user):
        creators.append({
            "id": c.id,
            "name": c.name,
            "url": c.url or "",
        })

    # Custom domain status
    custom_domain = CustomDomain.objects.filter(user=user).first()
    domain_info = {
        "domain": custom_domain.domain if custom_domain else "",
        "is_active": custom_domain.is_active if custom_domain else False,
        "is_configured": bool(custom_domain and custom_domain.domain),
    }

    # Subscription / Payment status
    last_payment = UserPayment.objects.filter(user=user).order_by('-date').first()
    plan_name = "Free Plan"
    is_paid = False
    if last_payment and last_payment.is_active and last_payment.subscription:
        plan_name = last_payment.subscription.name
        is_paid = True

    # Available themes across Skillifly
    all_themes = []
    for t in Theme.objects.select_related('category').all():
        all_themes.append({
            "name": t.name,
            "category": t.category.name if t.category else "Video Editor",
        })

    return {
        "account": {
            "username": user.username,
            "public_url": f"https://skillifly.cloud/{user.username}",
            "is_public": profile.is_public if profile else False,
            "visits": profile.visits if profile else 0,
            "has_profile_picture": bool(profile and profile.picture),
        },
        "subscription": {
            "plan": plan_name,
            "is_paid": is_paid,
            "has_custom_domain": is_paid,
            "has_pdf_export": "annual" in plan_name.lower() or is_paid,
        },
        "custom_domain": domain_info,
        "personal_info": {
            "full_name": personal_info.full_name if personal_info else "",
            "title": personal_info.title if personal_info else "",
            "bio": personal_info.bio if personal_info else (profile.bio if profile else ""),
            "email": personal_info.email if personal_info else user.email,
            "phone": personal_info.phone if personal_info else (profile.phone_number if profile else ""),
            "booking_url": personal_info.booking_url if personal_info else "",
        },
        "theme": theme_info,
        "available_themes_in_platform": all_themes,
        "section_order": profile.section_order if profile else [],
        "section_visibility": profile.section_visibility if profile else {},
        "skills": skills,
        "projects": projects,
        "project_categories": categories,
        "experiences": experiences,
        "educations": educations,
        "links": links,
        "reviews": reviews,
        "creators": creators,
    }



def create_snapshot(user, description="Agent change", message=None):
    """Takes a snapshot of the user's current portfolio state before modifying."""
    state = get_portfolio_state(user)
    snapshot = PortfolioSnapshot.objects.create(
        user=user,
        message=message,
        snapshot_data=state,
        description=description,
    )
    return snapshot


@transaction.atomic
def restore_snapshot(user, snapshot_id):
    """Restores the user's portfolio to the state recorded in snapshot_id."""
    snapshot = get_object_or_404(PortfolioSnapshot, id=snapshot_id, user=user)
    data = snapshot.snapshot_data

    # 1. PersonalInfo & Profile
    p_info = data.get("personal_info", {})
    PersonalInfo.objects.update_or_create(
        user=user,
        defaults={
            "full_name": p_info.get("full_name", ""),
            "title": p_info.get("title", ""),
            "bio": p_info.get("bio", ""),
            "email": p_info.get("email", user.email),
            "phone": p_info.get("phone", ""),
            "booking_url": p_info.get("booking_url", ""),
        }
    )

    profile, _ = Profile.objects.get_or_create(user=user)
    profile.bio = p_info.get("bio", "")
    profile.phone_number = p_info.get("phone", "")
    profile.is_public = data.get("is_public", profile.is_public)
    profile.section_order = data.get("section_order", [])
    profile.section_visibility = data.get("section_visibility", {})

    theme_info = data.get("theme")
    if theme_info and "id" in theme_info:
        theme = Theme.objects.filter(id=theme_info["id"]).first()
        if theme:
            profile.theme = theme
    profile.save()

    # 2. Skills
    Skill.objects.filter(user=user).delete()
    for s_name in data.get("skills", []):
        Skill.objects.create(user=user, name=s_name)

    # 3. Links
    Link.objects.filter(user=user).delete()
    for l in data.get("links", []):
        Link.objects.create(user=user, platform=l["platform"], url=l["url"])

    # 4. Education
    Education.objects.filter(user=user).delete()
    for ed in data.get("educations", []):
        yr = ed.get("year") or 2020
        Education.objects.create(
            user=user,
            school=ed.get("school", ""),
            degree=ed.get("degree", ""),
            field=ed.get("field", ""),
            grade_year=date(int(yr), 1, 1),
        )

    # 5. Experiences
    Experience.objects.filter(user=user).delete()
    for exp in data.get("experiences", []):
        start_d = _parse_date(exp.get("start_date")) or date.today()
        end_d = _parse_date(exp.get("end_date"))
        Experience.objects.create(
            user=user,
            title=exp.get("title", ""),
            company=exp.get("company", ""),
            start_date=start_d,
            end_date=end_d,
            still_working=exp.get("still_working", not end_d),
            duration=0.0,
            details=exp.get("details", ""),
        )

    # 6. Projects & Categories
    Project.objects.filter(user=user).delete()
    for p in data.get("projects", []):
        cat = None
        if p.get("category"):
            cat, _ = ProjectCategory.objects.get_or_create(user=user, name=p["category"])
        Project.objects.create(
            user=user,
            title=p.get("title", ""),
            url=p.get("url", ""),
            video_type=p.get("video_type", "long"),
            details=p.get("details", ""),
            category=cat,
        )

    # 7. Client Reviews
    if "reviews" in data:
        ClientReview.objects.filter(user=user).delete()
        for rev in data["reviews"]:
            ClientReview.objects.create(
                user=user,
                user_name=rev.get("user_name", "Client"),
                user_title=rev.get("user_title", ""),
                content=rev.get("content", ""),
                rating=rev.get("rating", 5),
                is_featured=rev.get("is_featured", True),
            )

    # 8. Inspiring Creators
    if "creators" in data:
        Creator.objects.filter(user=user).delete()
        for c in data["creators"]:
            Creator.objects.create(
                user=user,
                name=c.get("name", ""),
                url=c.get("url", ""),
            )

    return {"success": True, "message": f"Successfully reverted to snapshot: {snapshot.description}"}


def _parse_date(date_str):
    """Helper to parse dates in YYYY-MM, YYYY-MM-DD, or YYYY format."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    try:
        if len(date_str) == 4 and date_str.isdigit():
            return date(int(date_str), 1, 1)
        if len(date_str) == 7:
            y, m = map(int, date_str.split("-"))
            return date(y, m, 1)
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


# =============================================================================
# Agent Tools (Callable by Gemini Function Calling)
# =============================================================================

def ask_clarification(user, question, missing_fields=None, quick_replies=None):
    """
    Invoked when user's intent requires more details before modifying their portfolio.
    """
    return {
        "clarification_needed": True,
        "question": question,
        "missing_fields": missing_fields or [],
        "quick_replies": quick_replies or [],
    }


def update_personal_info(user, full_name=None, title=None, bio=None, booking_url=None, phone=None, email=None):
    """
    Updates the user's personal identity, professional title, bio, or contact information.
    """
    with transaction.atomic():
        snapshot = create_snapshot(user, description="Update personal info")
        
        info, _ = PersonalInfo.objects.get_or_create(
            user=user,
            defaults={
                "full_name": user.get_full_name() or user.username,
                "title": "Video Editor",
                "email": user.email,
                "phone": "",
                "bio": "",
            }
        )

        diff = {}
        if full_name is not None and full_name.strip():
            diff["full_name"] = {"old": info.full_name, "new": full_name.strip()}
            info.full_name = full_name.strip()
        if title is not None and title.strip():
            diff["title"] = {"old": info.title, "new": title.strip()}
            info.title = title.strip()
        if bio is not None and bio.strip():
            diff["bio"] = {"old": info.bio, "new": bio.strip()}
            info.bio = bio.strip()
            # Also update profile bio
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.bio = bio.strip()
            profile.save(update_fields=["bio"])
        if booking_url is not None:
            diff["booking_url"] = {"old": info.booking_url, "new": booking_url.strip()}
            info.booking_url = booking_url.strip()
        if phone is not None:
            diff["phone"] = {"old": info.phone, "new": phone.strip()}
            info.phone = phone.strip()
        if email is not None and email.strip():
            diff["email"] = {"old": info.email, "new": email.strip()}
            info.email = email.strip()

        info.save()

        return {
            "success": True,
            "action_type": "update_personal_info",
            "message": "Personal information updated successfully.",
            "diff": diff,
            "snapshot_id": snapshot.id,
        }


def add_project(user, title, url="", video_type="long", category_name=None, details=""):
    """
    Adds a new video project or reel to the user's portfolio.
    """
    if not title or not title.strip():
        return ask_clarification(
            user,
            question="What is the title of the video project you would like to add?",
            missing_fields=["title"],
            quick_replies=["Commercial Reel", "Brand Promo", "YouTube Video"],
        )

    title = title.strip()
    video_type = "reel" if str(video_type).lower() in ["reel", "short", "tiktok"] else "long"

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add project '{title}'")

        category = None
        if category_name and category_name.strip():
            category, _ = ProjectCategory.objects.get_or_create(
                user=user,
                name=category_name.strip(),
            )

        project = Project.objects.create(
            user=user,
            title=title,
            url=url.strip() if url else "",
            video_type=video_type,
            category=category,
            details=details.strip() if details else "",
        )

        return {
            "success": True,
            "action_type": "add_project",
            "message": f"Added project '{project.title}' ({project.get_video_type_display()}).",
            "project": {
                "id": project.id,
                "title": project.title,
                "url": project.url,
                "video_type": project.video_type,
                "category": category.name if category else "",
            },
            "snapshot_id": snapshot.id,
        }


def update_project(user, project_id=None, title_query=None, title=None, url=None, video_type=None, category_name=None, details=None):
    """
    Updates an existing project by ID or by searching its title.
    """
    project = None
    if project_id:
        project = Project.objects.filter(user=user, id=project_id).first()
    elif title_query:
        project = Project.objects.filter(user=user, title__icontains=title_query).first()

    if not project:
        user_projects = list(Project.objects.filter(user=user).values_list("title", flat=True)[:5])
        return ask_clarification(
            user,
            question="Which project would you like to update? Here are some of your current projects:",
            missing_fields=["project_id"],
            quick_replies=user_projects,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Update project '{project.title}'")
        diff = {}

        if title is not None and title.strip():
            diff["title"] = {"old": project.title, "new": title.strip()}
            project.title = title.strip()
        if url is not None:
            diff["url"] = {"old": project.url, "new": url.strip()}
            project.url = url.strip()
        if video_type is not None:
            v_type = "reel" if str(video_type).lower() in ["reel", "short"] else "long"
            diff["video_type"] = {"old": project.video_type, "new": v_type}
            project.video_type = v_type
        if details is not None:
            diff["details"] = {"old": project.details, "new": details.strip()}
            project.details = details.strip()
        if category_name is not None:
            if category_name.strip():
                cat, _ = ProjectCategory.objects.get_or_create(user=user, name=category_name.strip())
                diff["category"] = {"old": project.category.name if project.category else "", "new": cat.name}
                project.category = cat
            else:
                project.category = None

        project.save()

        return {
            "success": True,
            "action_type": "update_project",
            "message": f"Updated project '{project.title}'.",
            "diff": diff,
            "snapshot_id": snapshot.id,
        }


def delete_project(user, project_id=None, title_query=None):
    """
    Deletes a project by ID or title.
    """
    project = None
    if project_id:
        project = Project.objects.filter(user=user, id=project_id).first()
    elif title_query:
        project = Project.objects.filter(user=user, title__icontains=title_query).first()

    if not project:
        user_projects = list(Project.objects.filter(user=user).values_list("title", flat=True)[:5])
        return ask_clarification(
            user,
            question="Which project would you like to delete?",
            missing_fields=["project_id"],
            quick_replies=user_projects,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete project '{project.title}'")
        title = project.title
        project.delete()

        return {
            "success": True,
            "action_type": "delete_project",
            "message": f"Deleted project '{title}'.",
            "snapshot_id": snapshot.id,
        }


def manage_skills(user, add_skills=None, remove_skills=None, replace_all=False):
    """
    Adds, removes, or completely updates the user's listed skills and software tools.
    """
    with transaction.atomic():
        snapshot = create_snapshot(user, description="Manage skills")
        existing_skills = set(Skill.objects.filter(user=user).values_list("name", flat=True))
        
        added = []
        removed = []

        if replace_all and add_skills is not None:
            Skill.objects.filter(user=user).delete()
            existing_skills.clear()

        if add_skills:
            for s in add_skills:
                s_clean = s.strip()
                if s_clean and s_clean not in existing_skills:
                    Skill.objects.create(user=user, name=s_clean)
                    existing_skills.add(s_clean)
                    added.append(s_clean)

        if remove_skills:
            for r in remove_skills:
                r_clean = r.strip()
                deleted_count, _ = Skill.objects.filter(user=user, name__iexact=r_clean).delete()
                if deleted_count > 0:
                    removed.append(r_clean)

        current_skills = list(Skill.objects.filter(user=user).values_list("name", flat=True))

        msg = []
        if added:
            msg.append(f"Added: {', '.join(added)}")
        if removed:
            msg.append(f"Removed: {', '.join(removed)}")
        summary = ". ".join(msg) if msg else "Skills updated."

        return {
            "success": True,
            "action_type": "manage_skills",
            "message": summary,
            "current_skills": current_skills,
            "snapshot_id": snapshot.id,
        }


def add_experience(user, title, company, start_date=None, end_date=None, still_working=False, details=""):
    """
    Adds work experience to the user's portfolio.
    """
    if not title or not company:
        return ask_clarification(
            user,
            question="What is your job title and the company name for this role?",
            missing_fields=["title", "company"],
            quick_replies=["Senior Video Editor", "Motion Designer", "Freelance Editor"],
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add experience at {company}")

        parsed_start = _parse_date(start_date) or date.today()
        parsed_end = _parse_date(end_date) if not still_working else None

        exp = Experience.objects.create(
            user=user,
            title=title.strip(),
            company=company.strip(),
            start_date=parsed_start,
            end_date=parsed_end,
            still_working=still_working or (parsed_end is None),
            duration=0.0,
            details=details.strip() if details else "",
        )

        return {
            "success": True,
            "action_type": "add_experience",
            "message": f"Added experience: {exp.title} at {exp.company}.",
            "experience": {
                "id": exp.id,
                "title": exp.title,
                "company": exp.company,
                "start_date": exp.start_date.strftime("%Y-%m"),
            },
            "snapshot_id": snapshot.id,
        }


def delete_experience(user, experience_id=None, company_query=None):
    """Deletes an experience record."""
    exp = None
    if experience_id:
        exp = Experience.objects.filter(user=user, id=experience_id).first()
    elif company_query:
        exp = Experience.objects.filter(user=user, company__icontains=company_query).first()

    if not exp:
        existing = [f"{e.title} at {e.company}" for e in Experience.objects.filter(user=user)[:5]]
        return ask_clarification(
            user,
            question="Which experience entry would you like to delete?",
            missing_fields=["experience_id"],
            quick_replies=existing,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete experience at {exp.company}")
        comp = f"{exp.title} at {exp.company}"
        exp.delete()

        return {
            "success": True,
            "action_type": "delete_experience",
            "message": f"Deleted experience: {comp}.",
            "snapshot_id": snapshot.id,
        }


def add_education(user, school, degree, field, grade_year=None):
    """Adds an education entry."""
    if not school or not degree:
        return ask_clarification(
            user,
            question="What is the school/university name and the degree or certificate?",
            missing_fields=["school", "degree"],
            quick_replies=["Bachelor's Degree", "Self-Taught / Online Courses", "Diploma"],
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add education at {school}")

        yr = 2022
        if grade_year:
            try:
                yr = int(str(grade_year)[:4])
            except Exception:
                yr = 2022

        edu = Education.objects.create(
            user=user,
            school=school.strip(),
            degree=degree.strip(),
            field=field.strip() if field else "Film / Media Production",
            grade_year=date(yr, 1, 1),
        )

        return {
            "success": True,
            "action_type": "add_education",
            "message": f"Added education: {edu.degree} from {edu.school}.",
            "snapshot_id": snapshot.id,
        }


def delete_education(user, education_id=None):
    """Deletes an education entry."""
    edu = Education.objects.filter(user=user, id=education_id).first() if education_id else None
    if not edu:
        existing = [f"{e.degree} - {e.school}" for e in Education.objects.filter(user=user)[:5]]
        return ask_clarification(
            user,
            question="Which education entry would you like to remove?",
            missing_fields=["education_id"],
            quick_replies=existing,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete education {edu.school}")
        desc = f"{edu.degree} - {edu.school}"
        edu.delete()

        return {
            "success": True,
            "action_type": "delete_education",
            "message": f"Deleted education: {desc}.",
            "snapshot_id": snapshot.id,
        }


def add_link(user, platform, url):
    """Adds a social or external link (YouTube, Instagram, LinkedIn, Vimeo, Behance, etc.)."""
    if not platform or not url:
        return ask_clarification(
            user,
            question="What platform is this link for (e.g., Instagram, YouTube, Behance) and what is the URL?",
            missing_fields=["platform", "url"],
            quick_replies=["Instagram", "YouTube", "LinkedIn", "Behance"],
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add link {platform}")
        link = Link.objects.create(
            user=user,
            platform=platform.strip().capitalize(),
            url=url.strip(),
        )

        return {
            "success": True,
            "action_type": "add_link",
            "message": f"Added {link.platform} link.",
            "link": {"id": link.id, "platform": link.platform, "url": link.url},
            "snapshot_id": snapshot.id,
        }


def delete_link(user, link_id=None, platform=None):
    """Deletes a link by ID or platform."""
    link = None
    if link_id:
        link = Link.objects.filter(user=user, id=link_id).first()
    elif platform:
        link = Link.objects.filter(user=user, platform__iexact=platform.strip()).first()

    if not link:
        existing = list(Link.objects.filter(user=user).values_list("platform", flat=True))
        return ask_clarification(
            user,
            question="Which link would you like to remove?",
            missing_fields=["link_id"],
            quick_replies=existing,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete link {link.platform}")
        plat = link.platform
        link.delete()

        return {
            "success": True,
            "action_type": "delete_link",
            "message": f"Removed {plat} link.",
            "snapshot_id": snapshot.id,
        }


def change_theme(user, theme_name):
    """
    Switches the portfolio's active theme (e.g., 'creative', 'minimal', 'monochrome', 'yellow', 'cyan', 'editorial_studio', 'cinematic').
    """
    theme = None
    theme_name_clean = theme_name.strip().lower().replace(" ", "_")

    # Try exact match or icontains
    themes = Theme.objects.all()
    for t in themes:
        norm = t.name.lower().replace(" ", "_")
        if norm == theme_name_clean or theme_name_clean in norm:
            theme = t
            break

    if not theme:
        available = [t.name for t in Theme.objects.all()[:6]]
        return ask_clarification(
            user,
            question=f"I couldn't find a theme named '{theme_name}'. Here are some popular themes you can choose from:",
            missing_fields=["theme_name"],
            quick_replies=available,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Change theme to {theme.name}")
        profile, _ = Profile.objects.get_or_create(user=user)
        old_theme = profile.theme.name if profile.theme else "None"
        profile.theme = theme
        profile.save(update_fields=["theme"])

        return {
            "success": True,
            "action_type": "change_theme",
            "message": f"Portfolio theme changed to '{theme.name}'.",
            "diff": {"theme": {"old": old_theme, "new": theme.name}},
            "snapshot_id": snapshot.id,
        }


def update_section_layout(user, section_order=None, section_visibility=None):
    """
    Updates the display order and visibility of portfolio sections.
    Valid section keys: 'projects', 'skills', 'experience', 'education', 'reviews', 'creators', 'links', 'contact'
    """
    from core.section_order import normalize_section_order, normalize_section_visibility, profile_theme_slug

    with transaction.atomic():
        snapshot = create_snapshot(user, description="Update section layout")
        profile, _ = Profile.objects.get_or_create(user=user)
        category = profile.theme.category.name.lower().replace(" ", "_") if (profile.theme and profile.theme.category) else "video_editor"
        theme = profile_theme_slug(profile)

        if section_order is not None:
            profile.section_order = normalize_section_order(section_order, category, theme)
        if section_visibility is not None:
            profile.section_visibility = normalize_section_visibility(section_visibility, category, theme)

        profile.save(update_fields=["section_order", "section_visibility"])

        return {
            "success": True,
            "action_type": "update_section_layout",
            "message": "Portfolio section layout updated.",
            "section_order": profile.section_order,
            "section_visibility": profile.section_visibility,
            "snapshot_id": snapshot.id,
        }


def add_client_review(user, client_name, content, rating=5, client_title=""):
    """Adds a client testimonial / review to the portfolio."""
    if not client_name or not content:
        return ask_clarification(
            user,
            question="What is the client or director's name and their testimonial review text?",
            missing_fields=["client_name", "content"],
            quick_replies=["5-Star Commercial Client", "Agency Producer Review"],
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add review from {client_name}")
        r_val = max(1, min(5, int(rating or 5)))
        review = ClientReview.objects.create(
            user=user,
            user_name=client_name.strip(),
            user_title=client_title.strip() if client_title else "Client",
            content=content.strip(),
            rating=r_val,
            is_featured=True,
        )

        return {
            "success": True,
            "action_type": "add_client_review",
            "message": f"Added review from '{review.user_name}' ({review.rating} stars).",
            "review": {
                "id": review.id,
                "client_name": review.user_name,
                "rating": review.rating,
                "content": review.content,
            },
            "snapshot_id": snapshot.id,
        }


def delete_client_review(user, review_id=None, client_name_query=None):
    """Deletes a client review."""
    review = None
    if review_id:
        review = ClientReview.objects.filter(user=user, id=review_id).first()
    elif client_name_query:
        review = ClientReview.objects.filter(user=user, user_name__icontains=client_name_query).first()

    if not review:
        existing = [r.user_name for r in ClientReview.objects.filter(user=user)[:5]]
        return ask_clarification(
            user,
            question="Which review would you like to delete?",
            missing_fields=["review_id"],
            quick_replies=existing,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete review from {review.user_name}")
        name = review.user_name
        review.delete()

        return {
            "success": True,
            "action_type": "delete_client_review",
            "message": f"Deleted review from '{name}'.",
            "snapshot_id": snapshot.id,
        }


def add_creator(user, name, url=""):
    """Adds an inspiring creator/director/filmmaker to the inspirational creators marquee."""
    if not name or not name.strip():
        return ask_clarification(
            user,
            question="Who is the creator, filmmaker, or director you'd like to add?",
            missing_fields=["name"],
            quick_replies=["David Fincher", "Denis Villeneuve", "Edgar Wright"],
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add creator '{name}'")
        creator = Creator.objects.create(
            user=user,
            name=name.strip(),
            url=url.strip() if url else "",
        )

        return {
            "success": True,
            "action_type": "add_creator",
            "message": f"Added '{creator.name}' to your inspiring creators marquee.",
            "creator": {"id": creator.id, "name": creator.name, "url": creator.url},
            "snapshot_id": snapshot.id,
        }


def delete_creator(user, creator_id=None, name_query=None):
    """Deletes an inspiring creator entry."""
    creator = None
    if creator_id:
        creator = Creator.objects.filter(user=user, id=creator_id).first()
    elif name_query:
        creator = Creator.objects.filter(user=user, name__icontains=name_query).first()

    if not creator:
        existing = list(Creator.objects.filter(user=user).values_list("name", flat=True)[:5])
        return ask_clarification(
            user,
            question="Which creator would you like to remove?",
            missing_fields=["creator_id"],
            quick_replies=existing,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete creator {creator.name}")
        name = creator.name
        creator.delete()

        return {
            "success": True,
            "action_type": "delete_creator",
            "message": f"Removed '{name}' from inspiring creators.",
            "snapshot_id": snapshot.id,
        }


def add_project_category(user, name):
    """Creates a new video project category (e.g. Commercials, Music Videos, Documentaries, Reels)."""
    if not name or not name.strip():
        return ask_clarification(
            user,
            question="What is the name of the new project category?",
            missing_fields=["name"],
            quick_replies=["Commercials", "Narrative", "Music Videos", "Reels & Shorts"],
        )

    name = name.strip()
    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Add category '{name}'")
        cat, created = ProjectCategory.objects.get_or_create(user=user, name=name)

        return {
            "success": True,
            "action_type": "add_project_category",
            "message": f"Category '{cat.name}' is ready.",
            "category": {"id": cat.id, "name": cat.name, "created": created},
            "snapshot_id": snapshot.id,
        }


def delete_project_category(user, category_id=None, name=None):
    """Deletes a project category."""
    cat = None
    if category_id:
        cat = ProjectCategory.objects.filter(user=user, id=category_id).first()
    elif name:
        cat = ProjectCategory.objects.filter(user=user, name__iexact=name.strip()).first()

    if not cat:
        existing = list(ProjectCategory.objects.filter(user=user).values_list("name", flat=True)[:5])
        return ask_clarification(
            user,
            question="Which category would you like to delete?",
            missing_fields=["category_id"],
            quick_replies=existing,
        )

    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Delete category '{cat.name}'")
        cname = cat.name
        cat.delete()

        return {
            "success": True,
            "action_type": "delete_project_category",
            "message": f"Deleted category '{cname}'.",
            "snapshot_id": snapshot.id,
        }


def set_portfolio_visibility(user, is_public=True):
    """Sets whether the portfolio is publicly visible or private."""
    with transaction.atomic():
        snapshot = create_snapshot(user, description=f"Set portfolio visibility to {'public' if is_public else 'private'}")
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_public = bool(is_public)
        profile.save(update_fields=["is_public"])

        status_text = "Public (visible at your link)" if profile.is_public else "Private (hidden from visitors)"
        return {
            "success": True,
            "action_type": "set_portfolio_visibility",
            "message": f"Portfolio visibility updated to: {status_text}.",
            "is_public": profile.is_public,
            "snapshot_id": snapshot.id,
        }

