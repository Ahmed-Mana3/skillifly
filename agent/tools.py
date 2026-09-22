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
        }# ---------------------------------------------------------------------------
# Portfolio Audit (goal-based, deterministic intelligence)
# ---------------------------------------------------------------------------

AUDIT_GOALS = {
    "client": {
        "label_en": "Winning new clients",
        "label_ar": "جذب عملاء جدد",
        "priorities": ["projects", "reviews", "links", "contact"],
        # Themes that read as premium when pitching new clients.
        "theme_fav": ["cinematic", "minimal", "pro", "monochrome", "editorial_studio"],
        "theme_reason_en": "matches high-ticket commercial work and reads as premium to clients.",
        "theme_reason_ar": "يناسب الأعمال التجارية الراقية ويعطي انطباعاً متميزاً لدى العملاء.",
    },
    "recruiter": {
        "label_en": "Getting hired",
        "label_ar": "الحصول على وظيفة",
        "priorities": ["experience", "education", "skills", "projects"],
        "theme_fav": ["pro", "minimal", "cinematic"],
        "theme_reason_en": "reads clean and broadcast-ready for hiring managers.",
        "theme_reason_ar": "يبدو احترافياً ومنظماً وواضحاً أمام مسؤولي التوظيف.",
    },
    "agency": {
        "label_en": "Partnering with agencies",
        "label_ar": "التعاون مع الوكالات",
        "priorities": ["projects", "categories", "reviews", "contact"],
        "theme_fav": ["cinematic", "editorial_studio", "minimal", "pro"],
        "theme_reason_en": "matches the curated, editorial finish agencies pitch their clients with.",
        "theme_reason_ar": "يعطي لمسة إخراجية تحريرية تليق بالوكالات عند عرضها للعملاء.",
    },
    "creator": {
        "label_en": "Growing as a creator",
        "label_ar": "النمو كصانع محتوى",
        "priorities": ["reels", "bio", "links", "contact"],
        "theme_fav": ["yellow", "cyan", "animated_dark", "creative"],
        "theme_reason_en": "has the high-energy, scroll-stopping feel that creator audiences respond to.",
        "theme_reason_ar": "يمتلك طاقة بصرية عالية تجذب جمهور السوشيال ميديا.",
    },
}

# Placeholder / broken project URLs should be flagged for the user to fix.
AUDIT_PLACEHOLDER_URLS = ("placeholder", "tobeadded", "to-be-added", "editme", "youtu.be/", "example.com")


def _goal_key_for(key, goal):
    """Whether a gap key directly serves the chosen goal's priorities."""
    return key in AUDIT_GOALS[goal]["priorities"]


def gaps_by_key(gaps, key):
    """Whether a gap with the given key already exists in the list."""
    return any(g.get("key") == key for g in gaps)


CLICHE_PHRASES = (
    "passionate", "love editing", "loves editing", "i love editing",
    "i am a passionate", "مونتير شغوف", "احب المونتاج", "أحب المونتاج",
)

# Generic skills companies see in every editor — a sign the portfolio shows
# breadth instead of a focused, marketable signature stack.
GENERIC_SKILLS = (
    "video editing", "editing", "post production", "post-production", "color grading",
    "sound design", "premiere pro", "after effects", "davinci resolve", "photoshop",
)

SKILLS_GOOD_BAND = (5, 10)


def audit_portfolio(user, goal="client"):
    """
    Analyzes a user's portfolio against their stated goal ('client', 'recruiter',
    'agency', or 'creator') and returns a structured, grounded assessment:
    score, strengths, gaps, prioritized recommendations, copy issues, and a
    theme suggestion that actually exists in the database.

    Each gap/recommendation is fully bilingual (``why`` / ``action`` +
    ``ar_why`` / ``ar_action``) so callers can render Arabic without an LLM.
    """
    state = get_portfolio_state(user)
    goal = goal if goal in AUDIT_GOALS else "client"
    goal_info = AUDIT_GOALS[goal]

    pi = state.get("personal_info", {})
    account = state.get("account", {})
    projects = state.get("projects", [])
    skills = state.get("skills", [])
    reviews = state.get("reviews", [])
    experiences = state.get("experiences", [])
    educations = state.get("educations", [])
    links = state.get("links", [])
    creators = state.get("creators", [])
    theme = state.get("theme") or {}
    theme_name = (theme.get("name") or "").lower().replace(" ", "_")
    section_order = state.get("section_order") or []
    section_visibility = state.get("section_visibility") or {}

    gaps = []
    strengths = []
    copy_issues = []

    # ======================= Personal info & bio quality =====================
    bio = (pi.get("bio") or "").strip()
    headline = (pi.get("title") or "").strip()
    has_avatar = bool(account.get("has_profile_picture"))

    if not bio or len(bio) < 40:
        gaps.append({
            "key": "bio",
            "why": "A thin or missing bio makes you look less experienced.",
            "action": "Write a bio",
            "ar_why": "النبذة القصيرة أو المفقودة تجعلك تبدو أقل خبرة.",
            "ar_action": "كتابة نبذة شخصية",
        })
    elif len(bio) < 100:
        gaps.append({
            "key": "bio_depth",
            "why": "Your bio works but is on the short side — one concrete proof point would make it land harder.",
            "action": "Expand your bio",
            "ar_why": "النبذة جيدة لكنها قصيرة بعض الشيء — إضافة دليل إنجاز واحد يجعلها أقوى.",
            "ar_action": "توسيع النبذة",
        })
    if bio:
        bio_lower = bio.lower()
        for phrase in CLICHE_PHRASES:
            if phrase in bio_lower:
                copy_issues.append(f"Bio contains the clich\u00e9 \"{phrase}\"")
                gaps.append({
                    "key": "bio_cliche",
                    "why": f"Your bio opens with a clich\u00e9 (\"{phrase}\") that dilutes your authority.",
                    "action": "Rewrite your bio",
                    "ar_why": f"النبذة تحتوي على لغة مبتذلة (\"{phrase}\") تضعف مصداقيتك.",
                    "ar_action": "إعادة كتابة النبذة",
                })
                break

    if not headline:
        gaps.append({
            "key": "headline",
            "why": "No professional headline shown — visitors can't tell at a glance what you do.",
            "action": "Set your headline",
            "ar_why": "لا يوجد عنوان مهني واضح — الزوار لا يعرفون تخصصك من النظرة الأولى.",
            "ar_action": "تحديد العنوان المهني",
        })
    elif len(headline) < 12:
        gaps.append({
            "key": "headline",
            "why": f"Your headline \"{headline}\" is too generic to stand out.",
            "action": "Sharpen your headline",
            "ar_why": f"عنوانك \"{headline}\" عام ولا يميزك عن غيرك.",
            "ar_action": "تحسين العنوان المهني",
        })

    if not has_avatar:
        gaps.append({
            "key": "avatar",
            "why": "No profile photo lowers trust and recall with clients.",
            "action": "Add a photo",
            "ar_why": "عدم وجود صورة شخصية يقلل الثقة وسرعة التذكر لدى العملاء.",
            "ar_action": "إضافة صورة شخصية",
        })

    # =============================== Projects ================================
    reel_count = sum(1 for p in projects if p.get("video_type") == "reel")
    long_count = len(projects) - reel_count

    if not projects:
        gaps.append({
            "key": "projects",
            "why": "No video projects: clients and recruiters can't judge your skill.",
            "action": "Add a project",
            "ar_why": "لا توجد مشاريع فيديو: لا يستطيع العملاء أو مسؤولو التوظيف تقييم مهارتك.",
            "ar_action": "إضافة مشروع",
        })
    else:
        strengths.append(f"{len(projects)} project(s): {reel_count} reels, {long_count} long-form")

        empty_details = [p["title"] for p in projects if not (p.get("details") or "").strip()]
        if empty_details:
            gaps.append({
                "key": "project_details",
                "why": f"{len(empty_details)} project(s) have no description — context sells the craft.",
                "action": "Write project descriptions",
                "ar_why": f"{len(empty_details)} مشروع(ات) بدون وصف — السياق يبيع جودة العمل.",
                "ar_action": "كتابة وصف المشاريع",
            })

        no_category = [p["title"] for p in projects if not (p.get("category") or "")]
        if no_category:
            gaps.append({
                "key": "project_categories",
                "why": f"{len(no_category)} project(s) have no category tab — organized work looks more professional.",
                "action": "Organize projects into categories",
                "ar_why": f"{len(no_category)} مشروع(ات) بدون تصنيف — تنظيم العمل يبدو أكثر احترافية.",
                "ar_action": "تنظيم المشاريع في تصنيفات",
            })

        bad_urls = [
            p["title"] for p in projects
            if not (p.get("url") or "").strip() or any(t in (p.get("url") or "").lower() for t in AUDIT_PLACEHOLDER_URLS)
        ]
        if bad_urls:
            gaps.append({
                "key": "project_urls",
                "why": f"{len(bad_urls)} project(s) have a missing or placeholder video link.",
                "action": "Fix project URLs",
                "ar_why": f"{len(bad_urls)} مشروع(ات) بدون رابط فيديو صالح.",
                "ar_action": "إصلاح روابط المشاريع",
            })

        # Duplicate titles clutter the showcase and confuse visitors.
        seen_titles = {}
        duplicates = []
        for p in projects:
            key = (p.get("title") or "").strip().lower()
            seen_titles[key] = seen_titles.get(key, 0) + 1
            if seen_titles[key] == 2:
                duplicates.append(p.get("title"))
        if duplicates:
            gaps.append({
                "key": "project_duplicates",
                "why": f"Duplicate project title(s): {', '.join(duplicates[:3])} — your showcase repeats itself.",
                "action": "Rename or remove duplicates",
                "ar_why": f"توجد مشاريع بعناوين مكررة: {', '.join(duplicates[:3])} — عرضك يكرر نفسه.",
                "ar_action": "تعديل أو حذف العناوين المكررة",
            })

        # Format mix matters differently per goal.
        if goal == "creator" and reel_count == 0 and not gaps_by_key(gaps, "projects"):
            gaps.append({
                "key": "reels",
                "why": "No vertical reels — for a creator goal, short-form is your main growth channel.",
                "action": "Add a 9:16 reel",
                "ar_why": "لا توجد ريلز رأسية — لكي تنمو كصانع محتوى، الشورت فورم هو قناتك الأساسية.",
                "ar_action": "إضافة ريلز قصير (9:16)",
            })
        elif goal in ("recruiter", "agency") and long_count == 0 and not gaps_by_key(gaps, "projects"):
            gaps.append({
                "key": "long_form",
                "why": "No long-form (16:9) sample — agencies/recruiters expect to see narrative pacing.",
                "action": "Add a long-form project",
                "ar_why": "لا توجد عينة فيديو طويل (16:9) — الوكالات ومسؤولو التوظيف يتوقعون رؤية إيقاع سردي.",
                "ar_action": "إضافة مشروع طويل (16:9)",
            })

    # ================================= Skills ================================
    if not skills:
        gaps.append({
            "key": "skills",
            "why": "No listed skills/software stack.",
            "action": "Add skills",
            "ar_why": "لا توجد مهارات أو برامج مذكورة.",
            "ar_action": "إضافة مهارات",
        })
    else:
        if SKILLS_GOOD_BAND[0] <= len(skills) <= SKILLS_GOOD_BAND[1]:
            strengths.append(f"{len(skills)} skills listed")
        elif len(skills) > SKILLS_GOOD_BAND[1]:
            gaps.append({
                "key": "skills_focus",
                "why": f"{len(skills)} skills is overload — a giant list reads unfocused. Keep your strongest 5-8 signature tools.",
                "action": "Focus your skills",
                "ar_why": f"{len(skills)} مهارة كثير جداً — القائمة الطويلة توحي بالتشتت. اجعلها 5-8 أدوات أساسية فقط.",
                "ar_action": "تركيز المهارات",
            })
        else:
            strengths.append(f"{len(skills)} skills listed")

        # If every skill is generic, the stack doesn't tell a hiring story.
        generic_count = sum(1 for s in skills if s.strip().lower() in GENERIC_SKILLS)
        if len(skills) >= 4 and generic_count >= max(2, len(skills) // 2):
            copy_issues.append(
                "Skills advertise only generic tools — add a specialty or creative craft (sound design for narrative, motion GFX, etc.)."
            )

    # =============================== Reviews ================================
    if not reviews:
        gaps.append({
            "key": "reviews",
            "why": "No client testimonials: social proof = faster decisions.",
            "action": "Add a client review",
            "ar_why": "لا توجد آراء عملاء: الإثبات الاجتماعي يسّرع اتخاذ القرار.",
            "ar_action": "إضافة تقييم عميل",
        })
    elif len(reviews) == 1:
        strengths.append("1 client review")
        gaps.append({
            "key": "reviews_more",
            "why": "Only one testimonial — a second opinion from a different kind of client adds credibility.",
            "action": "Add another client review",
            "ar_why": "يوجد تقييم واحد فقط — إضافة رأي ثانٍ من نوع مختلف من العملاء يزيد المصداقية.",
            "ar_action": "إضافة تقييم عميل آخر",
        })
    else:
        strengths.append(f"{len(reviews)} client review(s)")

    # ========================= Experience / Education ========================
    if not experiences:
        gaps.append({
            "key": "experience",
            "why": "No work history shown.",
            "action": "Add experience",
            "ar_why": "لا توجد خبرات عمل معروضة.",
            "ar_action": "إضافة خبرة",
        })
    else:
        strengths.append(f"{len(experiences)} experience entry(ies)")
        undetailed_exp = [e.get("title") for e in experiences if not (e.get("details") or "").strip()]
        if undetailed_exp:
            gaps.append({
                "key": "experience_details",
                "why": f"{len(undetailed_exp)} experience entry(ies) have no description of your impact.",
                "action": "Describe your responsibilities",
                "ar_why": f"{len(undetailed_exp)} خب(ر)رة بدون وصف لدورك وأثرك.",
                "ar_action": "وصف مسؤولياتك",
            })

    if not educations:
        gaps.append({
            "key": "education",
            "why": "No education or certifications listed.",
            "action": "Add education",
            "ar_why": "لا توجد مؤهلات دراسية أو شهادات مذكورة.",
            "ar_action": "إضافة تعليم",
        })

    # =============================== Links & contact =========================
    if not links:
        gaps.append({
            "key": "links",
            "why": "No social/professional links.",
            "action": "Add links",
            "ar_why": "لا توجد روابط سوشيال أو روابط مهنية.",
            "ar_action": "إضافة روابط",
        })

    if not (pi.get("phone") or pi.get("email") or pi.get("booking_url")):
        gaps.append({
            "key": "contact",
            "why": "No visible contact method or booking link.",
            "action": "Add contact info",
            "ar_why": "لا توجد وسيلة تواصل أو رابط حجز ظاهر.",
            "ar_action": "إضافة معلومات التواصل",
        })

    # ============================== Visibility ==============================
    if not account.get("is_public"):
        gaps.append({
            "key": "visibility",
            "why": "Portfolio is private — no one can visit your link.",
            "action": "Publish portfolio",
            "ar_why": "المعرض خاص — لا يمكن لأحد زيارة رابطك.",
            "ar_action": "نشر المعرض",
        })

    # ===================== Hidden sections that have content =================
    section_map = {
        "projects": projects, "skills": skills, "experience": experiences,
        "education": educations, "reviews": reviews, "links": links,
        "creators": creators, "contact": [1] if (pi.get("phone") or pi.get("email") or pi.get("booking_url")) else [],
    }
    hidden_with_content = []
    for key, content in section_map.items():
        if content and section_visibility.get(key) is False:
            hidden_with_content.append(key)
    if hidden_with_content:
        gaps.append({
            "key": "hidden_sections",
            "why": f"You have content in {', '.join(hidden_with_content)} but the section is hidden from visitors.",
            "action": "Show hidden sections",
            "ar_why": f"لديك محتوى في {', '.join(hidden_with_content)} لكن القسم مخفي عن الزوار.",
            "ar_action": "إظهار الأقسام المخفية",
        })

    # ============================== Score ===================================
    # Graduated, goal-aware deduction model.
    deductions = {
        "bio": 12, "bio_depth": 2, "bio_cliche": 4, "headline": 4, "avatar": 3,
        "projects": 22, "project_details": 6, "project_categories": 2, "project_urls": 3,
        "project_duplicates": 3, "reels": 4, "long_form": 4,
        "skills": 10, "skills_focus": 2,
        "reviews": 10, "reviews_more": 2, "experience": 8, "experience_details": 2,
        "education": 2,
        "links": 5, "contact": 7, "visibility": 8, "hidden_sections": 3,
    }
    # Goal-critical sections cost extra — a strong portfolio for the wrong goal
    # is weaker than one that fills its target funnel first.
    goal_priority_keys = set(goal_info["priorities"])

    score = 100
    seen = set()
    for gap in gaps:
        key = gap["key"]
        base = deductions.get(key, 0)
        if key in goal_priority_keys:
            base = min(base + 2, 22)
        if key not in seen:
            score -= base
            seen.add(key)
    # Copy issues (graphical polish) cost a small flat amount once.
    if copy_issues:
        score -= 3
    score = max(0, min(100, score))

    # ========================= Goal fit assessment ==========================
    # Extra insight: how well does the portfolio fill the goal's funnel?
    goal_filled = [k for k in goal_info["priorities"] if k not in seen]
    if goal_filled:
        strengths.append(f"Goal fit ({goal}): {', '.join(goal_filled)} covered")

    # ====================== Theme suggestion (grounded) =====================
    suggestion = None
    for cand in goal_info["theme_fav"]:
        match = Theme.objects.filter(name__iexact=cand).first()
        if match:
            suggestion = {
                "name": match.name,
                "preview": f"/preview/{match.name.lower().replace(' ', '_')}",
                "reason_en": goal_info["theme_reason_en"],
                "reason_ar": goal_info["theme_reason_ar"],
            }
            break
    if suggestion:
        suggestion["is_active"] = (suggestion["name"].lower().replace(" ", "_") == theme_name)

    # =================== Goal-specific prioritized actions ==================
    recommendations = []
    for gap in gaps:
        key = gap["key"]
        if key in goal_priority_keys or key == "visibility":
            priority = "high" if key in goal_info["priorities"][:2] else "medium"
            recommendations.append({
                "priority": priority, "key": key,
                "why": gap["why"], "action": gap["action"],
                "ar_why": gap.get("ar_why", gap["why"]), "ar_action": gap.get("ar_action", gap["action"]),
            })
    recommendations.sort(key=lambda r: (0 if r["priority"] == "high" else 1, r["key"]))

    # Quick wins: anything non-goal-critical but cheap to fix (extra polish).
    quick_wins = [
        {"key": g["key"], "action": g["action"], "ar_action": g.get("ar_action", g["action"])}
        for g in gaps if g["key"] not in goal_priority_keys and g["key"] != "visibility"
    ]

    if score >= 85:
        summary = "Excellent portfolio — strong professional foundation."
        ar_summary = "معرض أعمال ممتاز — أساس احترافي قوي."
    elif score >= 65:
        summary = "Solid portfolio with a few quick wins left."
        ar_summary = "معرض جيد مع بعض التحسينات السريعة المتبقية."
    else:
        summary = "Getting there — this portfolio needs its foundation filled in."
        ar_summary = "في الطريق — يحتاج المعرض لملء الأساسيات."

    audit = {
        "goal": goal,
        "score": score,
        "summary": summary,
        "ar_summary": ar_summary,
        "strengths": strengths,
        "gaps": gaps,
        "copy_issues": copy_issues,
        "recommendations": recommendations,
        "quick_wins": quick_wins,
        "theme_suggestion": suggestion,
        "counts": {
            "projects": len(projects), "reels": reel_count, "long": long_count,
            "skills": len(skills), "reviews": len(reviews), "skills_focus": len(skills) > SKILLS_GOOD_BAND[1],
            "experience": len(experiences), "education": len(educations),
            "links": len(links), "hidden_sections": hidden_with_content,
        },
    }
    return {
        "success": True,
        "action_type": "audit_portfolio",
        "message": summary,
        "audit": audit,
        "snapshot_id": None,
    }