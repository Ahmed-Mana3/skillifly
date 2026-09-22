"""
Groq AI orchestration service for Skillifly Agent.
Uses Groq's OpenAI-compatible API with llama-3.3-70b-versatile for function calling.
Falls back to a smart local mode when no valid key is present.
"""

import os
import json
import logging
import random
import re
from django.conf import settings

try:
    from groq import Groq
except ImportError:
    Groq = None

from core.models import AgentConversation, AgentMessage, CustomUser, Theme
from core.ai import write_bio as ai_write_bio, GenerationService, generation_provider
from agent.tools import (
    get_portfolio_state,
    update_personal_info,
    add_project,
    update_project,
    delete_project,
    manage_skills,
    add_experience,
    delete_experience,
    add_education,
    delete_education,
    add_link,
    delete_link,
    change_theme,
    update_section_layout,
    add_client_review,
    delete_client_review,
    add_creator,
    delete_creator,
    add_project_category,
    delete_project_category,
    set_portfolio_visibility,
    audit_portfolio,
    ask_clarification,
    restore_snapshot,
)

logger = logging.getLogger(__name__)

TOOL_MAP = {
    "ask_clarification": ask_clarification,
    "update_personal_info": update_personal_info,
    "add_project": add_project,
    "update_project": update_project,
    "delete_project": delete_project,
    "manage_skills": manage_skills,
    "add_experience": add_experience,
    "delete_experience": delete_experience,
    "add_education": add_education,
    "delete_education": delete_education,
    "add_link": add_link,
    "delete_link": delete_link,
    "change_theme": change_theme,
    "update_section_layout": update_section_layout,
    "add_client_review": add_client_review,
    "delete_client_review": delete_client_review,
    "add_creator": add_creator,
    "delete_creator": delete_creator,
    "add_project_category": add_project_category,
    "delete_project_category": delete_project_category,
    "set_portfolio_visibility": set_portfolio_visibility,
    "audit_portfolio": audit_portfolio,
}


# ---------------------------------------------------------------------------
# Guided Multi-Step Workflows (deterministic wizards handled before any LLM call)
# ---------------------------------------------------------------------------

# Theme name (normalized to lowercase + underscores) -> light vs dark look.
WORKFLOW_LIGHT_THEMES = {
    "minimal",
    "pro",
    "creative_white",
    "animated",
    "categories_white",
    "editorial_studio",
}
WORKFLOW_DARK_THEMES = {
    "creative",
    "animated_dark",
    "categories",
    "monochrome",
    "yellow",
    "cyan",
}

WORKFLOW_CANCEL_WORDS = (
    "cancel", "stop", "never mind", "forget it", "actually not", "skip",
    "الغاء", "إلغاء", "لاغي", "توقف", "مش عايز", "خلاص مفيش",
)



# ---------------------------------------------------------------------------
# Tool Schemas (OpenAI-compatible JSON Schema format used by Groq)
# ---------------------------------------------------------------------------

GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "Ask the user clarifying questions when their request is missing required details or is ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The clear, friendly clarifying question to ask the user."},
                    "missing_fields": {"type": "array", "items": {"type": "string"}, "description": "List of field names that are needed."},
                    "quick_replies": {"type": "array", "items": {"type": "string"}, "description": "2 to 5 short clickable quick-reply option strings."},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_personal_info",
            "description": "Update user's personal details: name, professional title, bio, booking link, phone, or email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string", "description": "User full display name."},
                    "title": {"type": "string", "description": "Professional headline (e.g. Commercial & Documentary Video Editor)."},
                    "bio": {"type": "string", "description": "Engaging, high-converting professional bio."},
                    "booking_url": {"type": "string", "description": "Calendly or contact booking URL."},
                    "phone": {"type": "string", "description": "Contact phone or WhatsApp number."},
                    "email": {"type": "string", "description": "Contact email."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_project",
            "description": "Add a new video project, commercial, or vertical reel to the user's showcase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Video project title."},
                    "url": {"type": "string", "description": "Video link (YouTube, Vimeo, Google Drive, Instagram Reel)."},
                    "video_type": {"type": "string", "description": "'long' for 16:9 widescreen videos, or 'reel' for 9:16 vertical shorts/reels."},
                    "category_name": {"type": "string", "description": "Category (e.g. Commercials, Music Videos, Narrative, Reels)."},
                    "details": {"type": "string", "description": "Short description, software used, or client name."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project",
            "description": "Update an existing project by project_id or searching its title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Existing project ID if known."},
                    "title_query": {"type": "string", "description": "Search keyword or name of the project."},
                    "title": {"type": "string", "description": "New project title."},
                    "url": {"type": "string", "description": "New video URL."},
                    "video_type": {"type": "string", "description": "'long' or 'reel'."},
                    "category_name": {"type": "string", "description": "Category name."},
                    "details": {"type": "string", "description": "Updated project details."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project",
            "description": "Remove a project from the portfolio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID."},
                    "title_query": {"type": "string", "description": "Project title to match."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_skills",
            "description": "Add, remove, or replace user software skills (e.g., Premiere Pro, After Effects, DaVinci Resolve, Blender, Sound Design).",
            "parameters": {
                "type": "object",
                "properties": {
                    "add_skills": {"type": "array", "items": {"type": "string"}, "description": "List of skills to add."},
                    "remove_skills": {"type": "array", "items": {"type": "string"}, "description": "List of skills to remove."},
                    "replace_all": {"type": "boolean", "description": "Set to true to replace all existing skills with add_skills."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_experience",
            "description": "Add work experience or agency/freelance role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Job title (e.g. Lead Video Editor)."},
                    "company": {"type": "string", "description": "Company, studio, or client name."},
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM format (omit if current)."},
                    "still_working": {"type": "boolean", "description": "True if currently working here."},
                    "details": {"type": "string", "description": "Key responsibilities, tools, and achievements."},
                },
                "required": ["title", "company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_experience",
            "description": "Remove an experience entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experience_id": {"type": "integer", "description": "Experience ID."},
                    "company_query": {"type": "string", "description": "Company name to match."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_education",
            "description": "Add education, university degree, or certification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "Institution name."},
                    "degree": {"type": "string", "description": "Degree or certificate title."},
                    "field": {"type": "string", "description": "Field of study."},
                    "grade_year": {"type": "integer", "description": "Graduation year."},
                },
                "required": ["school", "degree"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_education",
            "description": "Remove an education entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "education_id": {"type": "integer", "description": "Education ID."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_link",
            "description": "Add an external social or portfolio link (Instagram, YouTube, Behance, Vimeo, LinkedIn, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "Platform name."},
                    "url": {"type": "string", "description": "Full URL."},
                },
                "required": ["platform", "url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_link",
            "description": "Remove an external link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {"type": "integer", "description": "Link ID."},
                    "platform": {"type": "string", "description": "Platform name to match."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_theme",
            "description": "Switch the portfolio visual theme.",
            "parameters": {
                "type": "object",
                "properties": {
                    "theme_name": {
                        "type": "string",
                        "description": "Theme name (e.g., 'creative', 'minimal', 'cinematic', 'yellow', 'cyan', 'monochrome', 'editorial_studio', 'pro').",
                    },
                },
                "required": ["theme_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_section_layout",
            "description": "Reorder sections or toggle section visibility.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_order": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ordered section keys ('projects', 'skills', 'experience', 'education', 'reviews', 'creators', 'links', 'contact').",
                    },
                    "section_visibility": {
                        "type": "object",
                        "description": "Dictionary of section_key -> boolean (e.g. {'education': false}).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_client_review",
            "description": "Add a client testimonial or review to the portfolio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string", "description": "Name of the client, director, or producer."},
                    "content": {"type": "string", "description": "The testimonial review text."},
                    "rating": {"type": "integer", "description": "Rating from 1 to 5 stars (default 5)."},
                    "client_title": {"type": "string", "description": "Title or company of client (e.g. Commercial Director, Nike Agency)."},
                },
                "required": ["client_name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_client_review",
            "description": "Remove a client review from the portfolio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "review_id": {"type": "integer", "description": "ID of review if known."},
                    "client_name_query": {"type": "string", "description": "Client name to match."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_creator",
            "description": "Add an inspiring director, filmmaker, or creative to the inspirational creators marquee.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Creator or director name (e.g. David Fincher, Denis Villeneuve)."},
                    "url": {"type": "string", "description": "Optional social, IMDb, or portfolio URL."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_creator",
            "description": "Remove an inspiring creator from the marquee.",
            "parameters": {
                "type": "object",
                "properties": {
                    "creator_id": {"type": "integer", "description": "Creator ID if known."},
                    "name_query": {"type": "string", "description": "Name to match."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_project_category",
            "description": "Create a new video project category tab (e.g. Commercials, Music Videos, Narrative, Documentary, Reels).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Category name."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project_category",
            "description": "Delete a project category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_id": {"type": "integer", "description": "Category ID if known."},
                    "name": {"type": "string", "description": "Category name to match."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_portfolio_visibility",
            "description": "Toggle whether the portfolio is publicly visible on the web or private.",
            "parameters": {
                "type": "object",
                "properties": {
                    "is_public": {"type": "boolean", "description": "True to publish publicly, False to make private."},
                },
                "required": ["is_public"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_portfolio",
            "description": "Run a goal-based audit of the user's portfolio: completeness score, strengths, gaps, prioritized recommendations, copy issues, and a theme suggestion. Call this whenever the user asks to audit, review, or improve their portfolio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "enum": ["client", "recruiter", "agency", "creator"],
                        "description": "What the user wants to achieve with the portfolio. Default 'client'.",
                    },
                },
            },
        },
    },
]



# ---------------------------------------------------------------------------
# Comprehensive System Prompt Builder
# ---------------------------------------------------------------------------

def _build_system_prompt(user, portfolio_state, language="en"):
    """
    Creates an exhaustive, domain-mastery system prompt equipping the LLM
    with complete knowledge of the Skillifly SaaS platform, video editing workflows,
    design aesthetics, and the user's real-time portfolio data.
    """
    is_ar = language == "ar"
    smooth_reading_rules = (
        "- **Smooth reading:** Write in short, complete sentences that flow naturally.\n"
        "- Never use telegraphic fragments; every line must read as a real sentence.\n"
        "- When you list things, open with one short lead-in sentence, then one clean bullet per idea.\n"
        "- Your reply may be read aloud by a voice assistant (TTS): keep the phrasing conversational, avoid symbols, and let each sentence breathe by itself."
        if is_ar else
        "- **Smooth reading:** Write in short, complete sentences that flow naturally from one to the next.\n"
        "- Never use telegraphic fragments; every line must read as a real sentence.\n"
        "- When you list things, open with one short lead-in sentence, then one clean bullet per idea.\n"
        "- Your reply may be read aloud by a voice assistant (TTS): keep the phrasing conversational, avoid symbols, and let each sentence stand alone."
    )

    lang_directive = (
        "### Language & Cultural Directive:\n"
        "- The user is interacting in Arabic.\n"
        "- Respond in natural, professional, and direct Arabic (Egyptian dialect mixed with clean Modern Standard Arabic where appropriate).\n"
        "- STRICT BREVITY: Keep all responses SHORT, CLEAR, and DIRECT TO THE POINT (1-2 sentences maximum).\n"
        "- Maintain industry terminology commonly used in the Arabic creative industry (e.g., مونتاج, كلر جريدنج, إعلانات تجارية, ريلز, تريلر, موشن جرافيكس).\n"
        "- All quick-reply pills, clarifying questions, and action summaries must be written in concise, fluent Arabic.\n"
        + smooth_reading_rules
        if is_ar else
        "### Language Directive:\n"
        "- The user is interacting in English.\n"
        "- Respond in polished, confident, and direct English with industry-savvy creative agency terminology.\n"
        "- STRICT BREVITY: Keep all responses SHORT, CLEAR, and DIRECT TO THE POINT (1-2 sentences maximum).\n"
        + smooth_reading_rules
    )

    state_json = json.dumps(portfolio_state, indent=2, ensure_ascii=False)

    # Compute quick portfolio health signals for the LLM to reason about
    pi = portfolio_state.get("personal_info", {})
    projects = portfolio_state.get("projects", [])
    skills = portfolio_state.get("skills", [])
    reviews = portfolio_state.get("reviews", [])
    experiences = portfolio_state.get("experiences", [])
    educations = portfolio_state.get("educations", [])
    links = portfolio_state.get("links", [])
    has_bio = bool((pi.get("bio") or "").strip() and len((pi.get("bio") or "").strip()) > 30)
    has_avatar = bool(portfolio_state.get("account", {}).get("has_profile_picture"))
    is_public = bool(portfolio_state.get("account", {}).get("is_public"))
    reel_count = sum(1 for p in projects if p.get("video_type") == "reel")

    gaps_summary = []
    if not has_bio:
        gaps_summary.append("bio")
    if not has_avatar:
        gaps_summary.append("photo")
    if not projects:
        gaps_summary.append("projects")
    elif any(not p.get("details") for p in projects):
        gaps_summary.append("project_descriptions")
    if not skills:
        gaps_summary.append("skills")
    if not reviews:
        gaps_summary.append("reviews")
    if not experiences:
        gaps_summary.append("experience")
    if not educations:
        gaps_summary.append("education")
    if not links:
        gaps_summary.append("links")
    if not is_public:
        gaps_summary.append("visibility")

    return f"""You are Skillifly AI — an elite Creative Director, Post-Production Producer, and Portfolio Architect built directly into Skillifly.
Your mission is to help video editors, colorists, motion designers, and filmmakers build a world-class, client-winning portfolio that lands high-ticket brand deals and agency contracts.

{lang_directive}

---

## 🎨 Response Formatting & Presentation (STRICT REQUIREMENT):
Every response you send MUST look clean, structured, and professionally crafted:
1. **Status indicators**: Start action confirmations with ✅. Start proactive suggestions with 📌. Use 🎨 for theme recommendations and ⭐ for reviews.
2. **Bold emphasis**: Always **bold** key values — project titles, theme names, skill names, section names, scores, and anything the user specifically asked about.
3. **Structured lists**: When listing multiple items or priorities, use clean numbered lists (1., 2., 3.) for ordered priorities, or bullet points (•) for unordered items. Each item on its own line.
4. **Section headers**: For audit results or multi-part responses, use bold section headers like **Strengths:** or **Priorities:** to separate different parts of the response.
5. **Action → Impact → Next**: For confirmations, follow: ✅ what changed → brief impact clause → 📌 one next-step suggestion (on new line).
6. **Quote user content**: When showing generated bios, review text, or project descriptions, wrap them in quotes ("...").
7. **Confident tone**: Write like an elite Creative Director briefing a client — authoritative, precise, warm but never casual. Never hedge with "maybe", "perhaps", "I think". State facts and recommendations with conviction.
8. **No filler**: Never open with "Certainly!", "Sure thing!", "Of course!", "Absolutely!", "Great choice!", "I would be happy to". Open directly with the action or answer.

---

## ⚡ Brevity, Clarity & Directness (STRICT REQUIREMENT):
1. **Be Short, Clear, and Direct to the Point**:
   - Limit your response to **1 to 2 sentences maximum** (3 at most if providing a brief bullet list).
   - NEVER use filler intros or conversational fluff (avoid "Certainly!", "I would be happy to help with that", "As an AI creative director...", "Here are the updates:").
   - Action first: state what was updated or ask the precise missing question immediately.
   - If providing suggestions, use at most 2-3 brief, punchy bullet points (1 line each). Never output long paragraphs.
2. **Direct Action Over Discussion**:
   - Execute the relevant tool immediately when requested. Confirm the action in 1 direct sentence.

---

## 🧠 Smart Reasoning Instructions:
1. **Chain of Thought (silent)**: Before deciding which tool to call, mentally analyze:
   - What exactly is the user asking? Be precise about intent.
   - Do I have ALL required information? If yes → execute immediately. If no → what specific detail is missing?
   - Can I infer reasonable defaults from the portfolio state? (e.g., if they have commercial projects, suggest "Commercials" as a category).
   - Should I make multiple tool calls in one response? (e.g., adding a project AND a category together).
2. **Conversational vs Action**: 
   - If the user is asking a question about their portfolio, the platform, or giving feedback — RESPOND CONVERSATIONALLY. Do NOT call tools when no modification is requested.
   - If the user wants to change/add/delete/update — CALL THE TOOL IMMEDIATELY.
   - Examples of conversational (NO tool call): "How does my portfolio look?", "What theme do you recommend?", "Can I add a custom domain?", "Thanks!"
   - Examples of action (TOOL call needed): "Add a project", "Change my bio", "Delete the review from John", "Switch to dark theme".
3. **Smart Defaults**: When adding items, use intelligent defaults from context:
   - If the user has `Commercials` as an existing category, new brand videos should probably go there.
   - If they use DaVinci Resolve, mention it in copy. If they have reels, suggest reel-optimized themes.
   - When suggesting quick replies, prefer actions that fill the BIGGEST GAP in their portfolio first.
4. **Proactive Coaching**: After completing an action, briefly suggest the single most impactful next step based on what's missing. Example: "Added your project. Your portfolio still needs a bio — want me to write one?"

---

## 🏛️ Comprehensive Skillifly Platform Knowledge Base:

### 1. What is Skillifly?
Skillifly (https://skillifly.cloud) is the leading portfolio builder designed specifically for the video post-production industry.
- Public Portfolio URL: `https://skillifly.cloud/<username>` (or a verified Custom Domain e.g. `https://alexmercer.film`).
- Theme Previews: Users can preview any theme at `/preview/<theme_name>` (e.g. `/preview/cinematic`, `/preview/creative`).
- Builder Interface: Live WYSIWYG editor with instant AJAX saves, section reordering, and modal previews at `/builder/` (or `/ar/builder/`).
- Full Bilingual Support: English (`/`) and Arabic (`/ar/`) with true right-to-left (RTL) typography, layout mirroring, and localized controls.

### 2. The Theme Catalogue & Aesthetic Profiles:
Skillifly features custom-crafted theme families tailored to specific creative niches:
- **`cinematic`**: Dark atmospheric letterbox aesthetic (2.39:1 aspect ratios), filmic grain, moody high-contrast lighting, bold typography.
  *Ideal for:* Feature film directors, trailer editors, narrative cinematographers, DaVinci Resolve colorists.
- **`creative`**: Vibrant color blocking, expressive type, interactive hover effects, high visual energy.
  *Ideal for:* Motion designers, music video directors, After Effects artists, short-form viral creators.
- **`minimal`**: Expansive whitespace, editorial typography, minimalist grids, timeless elegance.
  *Ideal for:* Commercial directors, documentary editors, high-end fashion and agency pitches.
- **`monochrome`**: High-contrast black-and-white, brutalist layout, sharp editorial edges.
  *Ideal for:* Luxury brands, high fashion films, experimental and arthouse video editors.
- **`yellow`**: Electric black-and-yellow neon accents, punchy thumbnails, high-retention creator energy.
  *Ideal for:* Top-tier YouTube editors (MrBeast, Ali Abdaal style), course creators, agency reels.
- **`cyan`**: Tech-forward neon cyan on deep navy/black, futuristic glow, cyber aesthetic.
  *Ideal for:* 3D animators (Blender/Unreal Engine), gaming montage artists, tech brand editors.
- **`editorial_studio`**: Magazine-grade editorial spreads, dramatic headline serif typography, agency finish.
  *Ideal for:* Boutique post-production houses, boutique commercial studios.
- **`pro`**: Corporate, television broadcast ready, clean structured modules.
  *Ideal for:* TV commercial editors, corporate documentary filmmakers, broadcast engineers.
- **`animated` / `animated_dark`**: Ambient floating video elements, interactive loop previews.

### 3. Dual-Format Video Player Architecture:
Skillifly natively solves the modern editor's biggest dilemma: Landscape vs. Vertical.
- **`long` (16:9 Landscape)**: Widescreen format for YouTube, Vimeo, cinema trailers, brand commercials.
- **`reel` (9:16 Vertical)**: Formatted for Instagram Reels, TikTok, YouTube Shorts. Displayed in an immersive, mobile-optimized reel player with auto-play and seamless swipe/scroll.
- **Supported Video Embeds**: YouTube (`watch?v=...`, `shorts/...`, `youtu.be/...`), Vimeo (`vimeo.com/...`), Google Drive direct preview links, and Instagram Reels (`instagram.com/reel/...`).

### 4. Portfolio Sections & Customization Hierarchy:
Users can organize and customize 8 primary portfolio sections:
1. `personal_info`: Full name, professional headline, bio, profile photo, booking link (Calendly/tidycal), WhatsApp/phone, email.
2. `projects`: Video showcase filterable by category tabs (e.g. Commercials, Music Videos, Reels).
3. `skills`: Technical software stack (Premiere, DaVinci, After Effects, etc.) and creative proficiencies.
4. `experience`: Employment, agency contracts, and freelance history with dates and descriptions.
5. `education`: Film schools, university degrees, masterclasses, and certified credentials.
6. `reviews`: 5-star client testimonials with reviewer name, company title, and quotes.
7. `creators`: "Inspiring Creators" marquee highlighting directors and cinematographers that influence the editor's visual taste.
8. `links`: Social and professional networks (YouTube, Vimeo, Instagram, Behance, LinkedIn, GitHub).
- **Layout Control**: Any section can be dragged/reordered (`update_section_layout`), or hidden completely if empty.

### 5. Plans, Custom Domains & Analytics:
- **Free Plan**: Unlimited video showcases, standard themes, hosted at `skillifly.cloud/<username>`.
- **Pro Monthly (99 EGP / 30 days)**: All themes unlocked, custom project categories, analytics dashboard.
- **Pro Annual (449 EGP / 365 days)**: Everything in Pro + **Custom Domain Connection** (e.g. `yourname.film` with automatic Let's Encrypt SSL).
- **Analytics**: 30-day visitor tracking, session duration, device breakdown, and per-project video play click events.

---

## 🎯 Creative Director Standard of Excellence:
When generating or modifying content for the user:
1. **Never write generic or cliché copy**: Avoid boring phrases like "I am a passionate video editor who loves editing". Instead, write high-converting copy focusing on **rhythm, emotional resonance, pacing, retention, color depth, sound design, and commercial ROI**.
2. **Highlight Industry Software & Workflows**: Emphasize Premiere Pro, DaVinci Resolve, ACES color management, After Effects, Fairlight audio mixing, sound staging, speed ramping, and match cutting.
3. **Smart Categorization**: When adding videos or categories, organize work into clean buckets like *"Commercials & Brand Films"*, *"Music Videos"*, *"Documentary Shorts"*, *"Vertical Reels & Social Ads"*.

---

## ⚡ User's Real-Time Portfolio State:
The JSON below reflects the user's exact live database records right now:
```json
{state_json}
```

### Portfolio Health Summary (pre-analyzed for you):
- **Existing gaps** (sections that need attention): {", ".join(gaps_summary) if gaps_summary else "None — portfolio is well-rounded!"}
- **Has bio**: {"Yes" if has_bio else "No — high priority gap"}
- **Has profile photo**: {"Yes" if has_avatar else "No"}
- **Projects count**: {len(projects)} ({reel_count} reels, {len(projects) - reel_count} long-form)
- **Skills count**: {len(skills)}
- **Reviews count**: {len(reviews)}
- **Experience entries**: {len(experiences)}
- **Links count**: {len(links)}
- **Portfolio public**: {"Yes" if is_public else "No — users should publish"}

Use this health summary to decide what to suggest next. ALWAYS prioritize filling the biggest gaps first.

---

## 🚨 Non-Negotiable Tool Calling Rules:
1. **Mandatory Execution**: Whenever the user asks to write, improve, add, delete, or change ANY detail in their portfolio (bio, headline, skills, experience, education, projects, reviews, creators, theme, categories, layout, visibility), **YOU MUST INVOKE THE RELEVANT TOOL FUNCTION IMMEDIATELY**.
   - NEVER simply say "I have updated your bio" in text without calling `update_personal_info`.
   - Calling the tool is what actually modifies the database. Conversational text alone changes nothing.
2. **Guided Wizards (handled by the system, not by you)**: The platform already runs deterministic step-by-step wizards for four intents and they never reach you:
   - **Adding a project**: asks for video **link first**, then **title**, then **long (16:9)** or **short reel (9:16)**.
   - **Changing the theme**: asks **light or dark**, then applies a matching theme.
   - **Writing a new bio**: asks **years of experience**, then **editing apps**, then **specialization**, then **extra details**.
   - **Adding a client review**: asks **testimonial text**, then **client name/company**, then **star rating (1-5)**.
   If the user references one of these wizards mid-conversation, simply acknowledge it — do NOT restart the questions.
3. **Clarification When Missing Required Information**: For all OTHER requests (e.g. adding experience, a link), if crucial details are missing, call `ask_clarification` with a short, direct question and 2 to 4 clickable `quick_replies`.
4. **Multi-Action Capability**: You can call multiple tools in sequence in a single response (e.g., updating bio AND adding 3 skills).
5. **Post-Action Conciseness**: After invoking tools, provide a 1-sentence confirmation of what was updated PLUS one proactive suggestion based on the biggest remaining gap (e.g., "Added your project. Your skills section is empty — want me to add your software stack?").
6. **Smart & Generic Recommendations**:
   - When suggesting next actions or quick replies, prioritize actions that fill the BIGGEST PORTFOLIO GAP first (check the Portfolio Health Summary above).
   - Keep quick replies GENERIC and ACTION-ORIENTED (e.g. "Change the theme", "Add a project", "Write a bio", "Add skills", "Add a client review", "Audit portfolio").
   - NEVER tell the user to change to a specific theme (e.g. do NOT say "Change theme to Cinematic", say "Change the theme").
7. **Audit Tool**: When the user asks to audit, review, improve, or get recommendations for their portfolio, CALL `audit_portfolio` FIRST (offer goal: getting clients / getting hired / working with agencies / growing as a creator). Then present its `score`, top `strengths`, and the top 2 `gaps` with their `action` in your short reply — never invent recommendations that the audit did not return.
8. **Conversational Mode**: When the user asks a QUESTION (not a request to modify), answer directly WITHOUT calling any tool. Only call tools when the user explicitly wants to change, add, delete, or create something.
"""


# ---------------------------------------------------------------------------
# Key Validation
# ---------------------------------------------------------------------------

def _is_placeholder_key(key: str) -> bool:
    if not key:
        return True
    k = str(key).strip().lower()
    return (
        k in ("your_gemini_api_key", "your_groq_api_key", "change-me", "placeholder",
               "none", "fake-key-for-test", "test", "")
        or k.startswith("your_")
        or len(k) < 12
    )


# ---------------------------------------------------------------------------
# AgentService
# ---------------------------------------------------------------------------

class AgentService:
    """Service to handle user messages, execute Groq LLM calls, and manage tool actions."""

    def __init__(self, user: CustomUser, conversation: AgentConversation = None, language: str = "en"):
        self.user = user
        self.language = language
        if conversation:
            self.conversation = conversation
        else:
            self.conversation, _ = AgentConversation.objects.get_or_create(
                user=user,
                is_active=True,
                defaults={"title": "Skillifly AI"},
            )

        self.api_key = (
            os.environ.get("GROQ_API_KEY", "")
            or getattr(settings, "GROQ_API_KEY", "")
        )
        self.is_placeholder_key = _is_placeholder_key(self.api_key)

        self.client = None
        if not self.is_placeholder_key and Groq is not None:
            try:
                self.client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to create Groq client: {e}")

        self.model_name = getattr(settings, "GROQ_AGENT_MODEL", "llama-3.3-70b-versatile")

    # -----------------------------------------------------------------------
    # Guided Multi-Step Workflows
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_url(text):
        m = re.search(r'https?://\S+', text or "")
        return m.group(0).strip().rstrip('.,;!)?') if m else ""

    @staticmethod
    def _extract_years(text):
        m = re.search(r'\b(\d{1,3})\b', text or "")
        return int(m.group(1)) if m else None

    @staticmethod
    def _is_dismissal(text):
        lower = (text or "").strip().lower()
        return any(
            k in lower
            for k in (
                "nothing", "no, that", "that's all", "thats all", "that is all",
                "nope", "not really", "that's it", "no extra",
                "لا شيء", "لا شئ", "مفيش", "لا", "خلص", "كفاية", "مجرد كده",
            )
        )

    def _set_workflow(self, state):
        self.conversation.workflow_state = state
        self.conversation.save(update_fields=["workflow_state"])

    def _clear_workflow(self):
        if self.conversation.workflow_state:
            self.conversation.workflow_state = None
            self.conversation.save(update_fields=["workflow_state"])

    def _cancel_pill(self, is_ar):
        return ["إلغاء"] if is_ar else ["Cancel"]

    def _detect_guided_intent(self, user_text):
        """Returns 'add_project', 'change_theme', 'bio', 'add_review', 'fix_project_url', 'reorder_sections', or None for a NEW request."""
        lower = (user_text or "").strip().lower()

        # 1. Client Review intent (check before general additions)
        review_phrases = (
            "add a review", "add review", "new review", "client review",
            "add client review", "add a testimonial", "add testimonial",
            "new testimonial", "add feedback", "client testimonial",
            "write a review", "give a review",
            "إضافة تقييم", "اضافة تقييم", "اضف تقييم", "أضف تقييم",
            "إضافة رأي", "اضافة رأي", "اضف رأي", "أضف رأي",
            "تقييم جديد", "رأي جديد", "تقييم عميل", "رأي عميل",
            "شهادة عميل", "عايز اضيف تقييم", "عايز أضيف تقييم",
            "اريد اضافة تقييم", "أريد إضافة تقييم", "عايز تقييم", "عايز اضيف رأي",
        )
        if any(p in lower for p in review_phrases):
            return "add_review"
        if ("review" in lower or "testimonial" in lower) and any(w in lower for w in ("add", "new", "create", "want", "help", "client")):
            return "add_review"
        if any(k in lower for k in ("تقييم", "رأي عميل", "شهادة عميل")) and any(
            w in lower for w in ("اضف", "أضف", "اضافة", "إضافة", "جديد", "اريد", "أريد", "عايز")
        ):
            return "add_review"

        # 1b. Fix project URL intent (before general add_project)
        fix_url_phrases = (
            "fix project url", "fix project urls", "fix project link", "fix project links",
            "update project url", "update project link", "update project links",
            "change project url", "change project link", "replace project url",
            "fix the url", "fix the link", "update the url", "update the link",
            "fix url", "fix link", "fix links", "fix urls",
            "fix project", "update project",
            "إصلاح رابط", "تحديث رابط", "تغيير رابط", "إصلاح روابط",
        )
        if any(p in lower for p in fix_url_phrases):
            return "fix_project_url"
        if ("project" in lower or "مشروع" in lower) and any(
            w in lower for w in ("url", "link", "رابط", "لينك")
        ) and any(w in lower for w in ("fix", "update", "change", "replace", "إصلاح", "تحديث", "تغيير")):
            return "fix_project_url"

        # 2. Add Project / Video intent
        add_project_phrases = (
            "add a project", "add project", "add a video", "add video",
            "add a reel", "add reel", "new project", "new video", "new reel",
            "create a project", "create project", "insert a project", "insert project",
            "إضافة مشروع", "اضافة مشروع", "اضف مشروع", "أضف مشروع",
            "إضافة فيديو", "اضافة فيديو", "إضافة ريلز", "اضافة ريلز",
            "مشروع جديد", "فيديو جديد", "ريلز جديد", "عايز اضيف مشروع", "عايز اضيف فيديو",
            "اريد اضافة مشروع", "أريد إضافة مشروع", "أريد إضافة فيديو", "عايز أضيف فيديو",
        )
        if any(p in lower for p in add_project_phrases):
            return "add_project"
        if ("project" in lower or "video" in lower or "reel" in lower) and "add" in lower:
            return "add_project"
        if any(k in lower for k in ("مشروع", "فيديو", "ريلز", "ريل")) and any(
            w in lower for w in ("اضف", "أضف", "اضافة", "إضافة", "جديد", "اريد", "أريد", "عايز")
        ):
            return "add_project"

        # 3. Theme intent
        theme_actions = ("change", "switch", "recommend", "pick", "choose", "new")
        if "theme" in lower and any(w in lower for w in theme_actions):
            return "change_theme"
        if any(k in lower for k in ("ثيم", "قالب")) and any(
            w in lower for w in ("غيّر", "غير", "تغيير", "بدّل", "بدل", "اقترح", "انصح", "جديد")
        ):
            return "change_theme"

        # 4. Bio intent
        if any(k in lower for k in ("bio", "biography", "نبذة", "نبذه", "سيرة ذاتية")):
            return "bio"

        # 5. Section Order intent
        order_phrases = (
            "change portfolio sections order", "change section order", "change sections order",
            "reorder sections", "section order", "sections order", "order of sections",
            "reorder portfolio", "change order of sections", "reorder my sections",
            "layout order", "reorder layout",
            "ترتيب أقسام المعرض", "ترتيب اقسام المعرض", "ترتيب الأقسام", "ترتيب الاقسام",
            "تغيير ترتيب الأقسام", "تغيير ترتيب الاقسام", "تغيير ترتيب أقسام", "تغيير ترتيب اقسام",
            "إعادة ترتيب الأقسام", "اعادة ترتيب الاقسام", "ترتيب معرض الأعمال", "ترتيب البورتفوليو",
        )
        if any(p in lower for p in order_phrases):
            return "reorder_sections"
        if ("order" in lower or "ترتيب" in lower) and any(w in lower for w in ("section", "sections", "portfolio", "أقسام", "اقسام", "معرض")):
            return "reorder_sections"

        return None

    def _pick_random_theme(self, tone):
        """Picks a random theme that matches the requested light/dark look."""
        wanted = WORKFLOW_LIGHT_THEMES if tone == "light" else WORKFLOW_DARK_THEMES
        matches, video_matches = [], []
        for t in Theme.objects.select_related("category").all():
            norm = (t.name or "").strip().lower().replace(" ", "_")
            if norm in wanted:
                is_video = "video" in (t.category.name.lower() if t.category else "")
                (video_matches if is_video else matches).append(t)
        pool = video_matches or matches
        return random.choice(pool).name if pool else None

    def _workflow_response(self, reply, quick_replies, actions=None, snapshot_id=None):
        agent_msg = AgentMessage.objects.create(
            conversation=self.conversation,
            sender="agent",
            text=reply,
            actions_applied=actions or None,
            quick_replies=quick_replies or None,
        )
        if snapshot_id:
            from core.models import PortfolioSnapshot
            PortfolioSnapshot.objects.filter(id=snapshot_id).update(message=agent_msg)
        return {
            "message": reply,
            "quick_replies": quick_replies,
            "actions": actions or [],
            "snapshot_id": snapshot_id,
            "agent_message_id": agent_msg.id,
            "portfolio_state": get_portfolio_state(self.user),
        }

    # -- Add Project wizard: link -> title -> long/short ----------------------

    def _start_add_project_workflow(self, user_text):
        is_ar = self.language == "ar"
        url = self._extract_url(user_text)
        if url:
            self._set_workflow({"type": "add_project", "step": "awaiting_title", "url": url})
            reply = (
                "تم استلام الرابط! ما هو عنوان المشروع؟"
                if is_ar else
                "Got the link! What is the project title?"
            )
            return self._workflow_response(reply, [])
        self._set_workflow({"type": "add_project", "step": "awaiting_url"})
        reply = (
            "أرسل رابط الفيديو (YouTube أو Vimeo أو Google Drive أو Reel):"
            if is_ar else
            "Please share the video link (YouTube, Vimeo, Google Drive, or Reel):"
        )
        return self._workflow_response(reply, self._cancel_pill(is_ar))

    def _advance_add_project(self, state, user_text):
        is_ar = self.language == "ar"
        step = state.get("step")
        lower = (user_text or "").strip().lower()

        if step == "awaiting_url":
            url = self._extract_url(user_text)
            if not url:
                reply = (
                    "يرجى إرسال رابط فيديو صالح (YouTube أو Vimeo أو Google Drive أو Reel):"
                    if is_ar else
                    "Please paste a valid video link (YouTube, Vimeo, Google Drive, or Reel):"
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))
            self._set_workflow({**state, "step": "awaiting_title", "url": url})
            reply = (
                "تم استلام الرابط! ما هو عنوان المشروع؟"
                if is_ar else
                "Got the link! What is the project title?"
            )
            return self._workflow_response(reply, [])

        if step == "awaiting_title":
            title = (user_text or "").strip().rstrip('.,')
            if len(title) < 2:
                reply = (
                    "ما هو عنوان المشروع؟ (مثال: «إعلان ريد بول 2024»)"
                    if is_ar else
                    "What's the title of the project? (e.g. \"Red Bull Ad 2024\")"
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))
            self._set_workflow({**state, "step": "awaiting_type", "title": title})
            reply = (
                f"هل «{title}» فيديو **طويل (16:9)** أم **ريلز قصير (9:16)**؟"
                if is_ar else
                f"Is \"{title}\" a **long video (16:9)** or a **short reel (9:16)**?"
            )
            quick = (
                ["فيديو طويل (16:9)", "ريلز قصير (9:16)"]
                if is_ar else
                ["Long video (16:9)", "Short reel (9:16)"]
            )
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        if step == "awaiting_type":
            v_type = None
            if any(k in lower for k in ("reel", "short", "vertical", "ريل", "ريلز", "قصير", "شورت", "tiktok")):
                v_type = "reel"
            elif any(k in lower for k in ("long", "wide", "landscape", "16:9", "16", "طويل", "افقي", "أفقي", "cinematic video")):
                v_type = "long"
            if not v_type:
                reply = (
                    "هل هذا فيديو طويل (16:9) أم ريلز قصير (9:16)؟"
                    if is_ar else
                    "Is this a long video (16:9) or a short reel (9:16)?"
                )
                quick = (
                    ["فيديو طويل (16:9)", "ريلز قصير (9:16)"]
                    if is_ar else
                    ["Long video (16:9)", "Short reel (9:16)"]
                )
                return self._workflow_response(reply, quick + self._cancel_pill(is_ar))
            res = add_project(
                self.user,
                title=state.get("title", "Featured Video Project"),
                url=state.get("url", ""),
                video_type=v_type,
            )
            self._clear_workflow()
            reply = (
                f"✅ تمت إضافة المشروع **«{state.get('title')}»** إلى معرض أعمالك بنجاح! 🎉"
                if is_ar else
                f"✅ Added **\"{state.get('title')}\"** to your portfolio! 🎉"
            )
            return self._workflow_response(reply, [], [res], res.get("snapshot_id"))

        return None


    # -- Fix project URL wizard: pick project -> paste link --------------------

    def _start_fix_project_url_workflow(self, user_text):
        is_ar = self.language == "ar"
        from core.models import Project
        projects = list(Project.objects.filter(user=self.user).values("id", "title"))
        if not projects:
            reply = (
                "لم أجد أي مشاريع. أضف مشروعاً أولاً!"
                if is_ar else
                "You don't have any projects yet. Add a project first!"
            )
            return self._workflow_response(
                reply,
                ["إضافة مشروع جديد"] if is_ar else ["Add a project"],
            )

        self._set_workflow({"type": "fix_project_url", "step": "awaiting_project_name"})
        reply = (
            "أي مشروع تريد تحديث رابطه؟"
            if is_ar else
            "Which project do you want to update the link for?"
        )
        pills = [p["title"] for p in projects[:6]] + self._cancel_pill(is_ar)
        return self._workflow_response(reply, pills)

    def _advance_fix_project_url(self, state, user_text):
        is_ar = self.language == "ar"
        step = state.get("step")

        if step == "awaiting_project_name":
            from core.models import Project
            # Try partial match on title
            project = Project.objects.filter(
                user=self.user, title__icontains=user_text.strip()
            ).first()
            if not project:
                # Exact match fallback
                for p in Project.objects.filter(user=self.user):
                    if user_text.strip().lower() == p.title.strip().lower():
                        project = p
                        break
            if not project:
                projects = list(Project.objects.filter(user=self.user).values("id", "title"))
                reply = (
                    "اختر مشروعاً من القائمة:"
                    if is_ar else
                    "Please pick a project from the list:"
                )
                pills = [p["title"] for p in projects[:6]] + self._cancel_pill(is_ar)
                return self._workflow_response(reply, pills)

            self._set_workflow({
                **state,
                "step": "awaiting_url",
                "project_id": project.id,
                "project_title": project.title,
            })
            reply = (
                f"شارك رابط «{project.title}»:"
                if is_ar else
                f'Share the link for "{project.title}":'
            )
            return self._workflow_response(reply, self._cancel_pill(is_ar))

        if step == "awaiting_url":
            url = self._extract_url(user_text)
            project_title = state.get("project_title", "this project")
            if not url:
                reply = (
                    "يرجى إرسال رابط صالح:"
                    if is_ar else
                    f'Please paste a valid link for "{project_title}":'
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))

            res = update_project(self.user, project_id=state.get("project_id"), url=url)
            self._clear_workflow()
            reply = (
                f"✅ تم تحديث رابط **«{project_title}»** بنجاح!"
                if is_ar else
                f"✅ Link updated for **\"{project_title}\"**!"
            )
            quick = (
                ["إصلاح رابط مشروع آخر", "إضافة مشروع جديد", "فحص معرض الأعمال"]
                if is_ar else
                ["Fix another project link", "Add a project", "Audit portfolio"]
            )
            return self._workflow_response(reply, quick, [res], res.get("snapshot_id"))

        return None

    # -- Change theme wizard: light or dark -> random recommendation ---------

    def _start_change_theme_workflow(self):
        is_ar = self.language == "ar"
        self._set_workflow({"type": "change_theme", "step": "awaiting_tone"})
        reply = (
            "هل تفضل الألوان **الفاتحة (Light)** أم **الداكنة (Dark)**؟"
            if is_ar else
            "Do you prefer **light** or **dark** colors?"
        )
        quick = ["فاتح", "داكن"] if is_ar else ["Light", "Dark"]
        return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

    def _advance_change_theme(self, state, user_text):
        is_ar = self.language == "ar"
        lower = (user_text or "").strip().lower()

        if any(k in lower for k in ("dark", "داكن", "غامق", "اسود", "أسود", "night")):
            tone = "dark"
        elif any(k in lower for k in ("light", "فاتح", "ابيض", "أبيض", "white", "bright", "مشرق", "ناصع")):
            tone = "light"
        else:
            reply = (
                "هل تفضل الألوان الفاتحة أم الداكنة؟"
                if is_ar else
                "Do you prefer light or dark colors?"
            )
            quick = ["فاتح", "داكن"] if is_ar else ["Light", "Dark"]
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        theme_name = self._pick_random_theme(tone)
        if not theme_name:
            self._clear_workflow()
            reply = (
                "لم أجد ثيماً متطابقاً حالياً."
                if is_ar else
                "Could not find a matching theme right now."
            )
            return self._workflow_response(reply, [])

        res = change_theme(self.user, theme_name)
        self._clear_workflow()
        reply = (
            f"✅ تم تغيير الثيم إلى **«{theme_name}»** بنجاح! 🎨"
            if is_ar else
            f"✅ Switched your portfolio to the **{theme_name}** theme! 🎨"
        )
        return self._workflow_response(reply, [], [res], res.get("snapshot_id"))

    # -- Bio wizard: years -> apps -> specialty -> extra ---------------------

    def _start_bio_workflow(self):
        is_ar = self.language == "ar"
        self._set_workflow({"type": "bio", "step": "awaiting_years"})
        reply = (
            "كم عدد **سنوات خبرتك (Years)** في المونتاج؟"
            if is_ar else
            "How many **years of experience** do you have in video editing?"
        )
        quick = (
            ["أقل من سنة", "1-3", "4-6", "7-10", "أكثر من 10"]
            if is_ar else
            ["Under 1", "1-3", "4-6", "7-10", "10+"]
        )
        return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

    def _years_phrase(self, years, is_ar):
        if years:
            return f"+{years} سنوات" if is_ar else f"{years}+ years"
        return "سنوات" if is_ar else "years"

    def _advance_bio(self, state, user_text):
        is_ar = self.language == "ar"
        step = state.get("step")
        text = (user_text or "").strip().rstrip('.,')

        if step == "awaiting_years":
            years = self._extract_years(user_text)
            if years is None:
                reply = (
                    "أرسل عدد سنوات خبرتك كرقم (مثال: 5):"
                    if is_ar else
                    "Please enter your years of experience as a number (e.g. 5):"
                )
                quick = (
                    ["أقل من سنة", "1", "3", "5", "10+"]
                    if is_ar else
                    ["Under 1", "1", "3", "5", "10+"]
                )
                return self._workflow_response(reply, quick + self._cancel_pill(is_ar))
            self._set_workflow({**state, "step": "awaiting_apps", "years": years})
            reply = (
                f"تمام، خبرة {self._years_phrase(years, True)}! ما **البرامج والأدوات (Apps)** التي تستخدمها؟"
                if is_ar else
                f"Got it, {self._years_phrase(years, False)}! Which **editing apps** or tools do you use?"
            )
            quick = (
                ["Premiere Pro", "DaVinci Resolve", "After Effects", "Final Cut Pro"]
                if not is_ar else
                ["بريمير برو", "دافينشي ريزولف", "أفتر إفكتس", "فاينال كت"]
            )
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        if step == "awaiting_apps":
            if len(text) < 2:
                reply = (
                    "ما البرامج التي تستخدمها في المونتاج؟"
                    if is_ar else
                    "Which apps do you use for editing?"
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))
            self._set_workflow({**state, "step": "awaiting_specialty", "apps": text})
            reply = (
                "ما هو **تخصصك الأساسي (Specialty)**؟ (إعلانات، ريلز، وثائقيات، أم عام):"
                if is_ar else
                "What is your **specialty**? (commercials, reels, documentaries, or general):"
            )
            quick = (
                ["إعلانات تجارية", "فيديوهات موسيقية", "ريلز وسوشيال ميديا", "وثائقيات", "عام"]
                if is_ar else
                ["Commercials", "Music videos", "Reels & social", "Documentaries", "Generalist"]
            )
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        if step == "awaiting_specialty":
            if len(text) < 2:
                reply = (
                    "ما تخصصك الأساسي؟"
                    if is_ar else
                    "What is your specialty?"
                )
                quick = (
                    ["إعلانات تجارية", "فيديوهات موسيقية", "ريلز وسوشيال ميديا", "عام"]
                    if is_ar else
                    ["Commercials", "Music videos", "Reels & social", "Generalist"]
                )
                return self._workflow_response(reply, quick + self._cancel_pill(is_ar))
            self._set_workflow({**state, "step": "awaiting_extra", "specialty": text})
            reply = (
                "هل هناك أي تفاصيل إضافية (anything else) تود إبرازها؟"
                if is_ar else
                "Is there anything else to highlight, or should we save it?"
            )
            quick = (
                ["لا شيء، هذا كل ما في الأمر", "سرعة التسليم وإتقان التفاصيل"]
                if is_ar else
                ["That's all", "Fast turnaround & high attention to detail"]
            )
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        if step == "awaiting_extra":
            extra = text
            if self._is_dismissal(extra):
                extra = ""
            bio = ai_write_bio(
                self.user,
                language=self.language,
                years=state.get("years"),
                apps=state.get("apps", ""),
                specialty=state.get("specialty", ""),
                extra=extra,
            )
            res = update_personal_info(self.user, bio=bio)
            self._clear_workflow()
            reply = (
                f"✅ تم تحديث النبذة بنجاح! ✍️\n\n\"{bio}\""
                if is_ar else
                f"✅ Updated your bio! ✍️\n\n\"{bio}\""
            )
            return self._workflow_response(reply, [], [res], res.get("snapshot_id"))

        return None

    # -- Review wizard: content -> client_name -> rating ----------------------

    def _start_add_review_workflow(self, user_text):
        is_ar = self.language == "ar"
        self._set_workflow({"type": "add_review", "step": "awaiting_client_name"})
        reply = (
            "ما اسم العميل؟"
            if is_ar else
            "What is the client's name?"
        )
        return self._workflow_response(reply, self._cancel_pill(is_ar))

    def _advance_add_review(self, state, user_text):
        is_ar = self.language == "ar"
        step = state.get("step")
        text = (user_text or "").strip()

        if step == "awaiting_client_name":
            clean_name = text.strip().rstrip(".,")
            if len(clean_name) < 2:
                reply = (
                    "ما اسم العميل؟"
                    if is_ar else
                    "What is the client's name?"
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))

            self._set_workflow({**state, "step": "awaiting_client_title", "client_name": clean_name})
            reply = (
                f"ما منصب أو لقب {clean_name}؟"
                if is_ar else
                f"What is {clean_name}'s position or title?"
            )
            return self._workflow_response(reply, self._cancel_pill(is_ar))

        if step == "awaiting_client_title":
            clean_title = text.strip().rstrip(".,")
            if len(clean_title) < 2:
                client_name = state.get("client_name", "")
                reply = (
                    f"ما منصب {client_name}؟"
                    if is_ar else
                    f"What is {client_name}'s position or title?"
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))

            self._set_workflow({**state, "step": "awaiting_content", "client_title": clean_title})
            client_name = state.get("client_name", "")
            reply = (
                f"ما نص تقييم {client_name}؟"
                if is_ar else
                f"What did {client_name} say? (paste their review)"
            )
            return self._workflow_response(reply, self._cancel_pill(is_ar))

        if step == "awaiting_content":
            clean_content = text.strip('" «»')
            if len(clean_content) < 4:
                reply = (
                    "يرجى كتابة نص التقييم:"
                    if is_ar else
                    "Please type the review content:"
                )
                return self._workflow_response(reply, self._cancel_pill(is_ar))

            self._set_workflow({**state, "step": "awaiting_rating", "content": clean_content})
            reply = (
                "كم تقييمه بالنجوم من 5؟"
                if is_ar else
                "Star rating out of 5?"
            )
            quick = ["⭐⭐⭐⭐⭐ (5)", "⭐⭐⭐⭐ (4)", "⭐⭐⭐ (3)"]
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        if step == "awaiting_rating":
            rating = 5
            m = re.search(r"[1-5]", text)
            if m:
                rating = int(m.group(0))
            elif "4" in text or "أربعة" in text or "اربعة" in text:
                rating = 4

            content = state.get("content", "")
            client_name = state.get("client_name", "Client")
            client_title = state.get("client_title", "")

            res = add_client_review(
                self.user,
                client_name=client_name,
                client_title=client_title,
                content=content,
                rating=rating,
            )
            self._clear_workflow()
            stars_str = "⭐" * rating
            title_part = f" — {client_title}" if client_title else ""
            reply = (
                f"✅ تمت إضافة التقييم! {stars_str}\n\n**{client_name}**{title_part}\n\"{content}\""
                if is_ar else
                f"✅ Review added! {stars_str}\n\n**{client_name}**{title_part}\n\"{content}\""
            )
            return self._workflow_response(reply, [], [res], res.get("snapshot_id"))

        return None

    # -- Reorder sections wizard: presets recommendation -> apply layout -------

    def _start_reorder_sections_workflow(self):
        is_ar = self.language == "ar"
        self._set_workflow({"type": "reorder_sections", "step": "awaiting_order"})
        reply = (
            "كيف تود ترتيب أقسام معرض أعمالك؟ يمكنك الاختيار من النماذج الجاهزة أدناه أو كتابة الترتيب المفضل لديك:"
            if is_ar else
            "How would you like to order your portfolio sections? Choose one of the quick presets below or describe your preferred order:"
        )
        quick = (
            ["مسؤول التوظيف أولاً", "العميل أولاً", "الإثبات الاجتماعي أولاً", "الافتراضي للثيم"]
            if is_ar else
            ["Recruiter first", "Client first", "Social proof first", "Theme default"]
        )
        return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

    def _advance_reorder_sections(self, state, user_text):
        is_ar = self.language == "ar"
        lower = (user_text or "").strip().lower()
        from core.section_order import SECTION_PRESETS

        chosen_order = None
        preset_name = None

        if any(w in lower for w in ("recruiter", "توظيف", "موظف")):
            chosen_order = SECTION_PRESETS["recruiter_first"]
            preset_name = "مسؤول التوظيف أولاً" if is_ar else "Recruiter first"
        elif any(w in lower for w in ("client", "عميل")):
            chosen_order = SECTION_PRESETS["client_first"]
            preset_name = "العميل أولاً" if is_ar else "Client first"
        elif any(w in lower for w in ("social", "proof", "اجتماعي", "إثبات", "اثبات")):
            chosen_order = SECTION_PRESETS["social_proof_first"]
            preset_name = "الإثبات الاجتماعي أولاً" if is_ar else "Social proof first"
        elif any(w in lower for w in ("default", "theme default", "افتراضي", "الافتراضي", "reset", "استعادة")):
            chosen_order = []
            preset_name = "الافتراضي للثيم" if is_ar else "Theme default"
        else:
            # Check for keyword extraction
            key_map = {
                "project": "projects", "work": "projects", "showcase": "projects", "مشاريع": "projects", "مشروع": "projects", "معرض": "projects",
                "skill": "skills", "مهارات": "skills", "مهارة": "skills",
                "experience": "experience", "خبرات": "experience", "خبرة": "experience",
                "education": "education", "تعليم": "education", "دراسة": "education",
                "review": "reviews", "testimonial": "reviews", "تقييم": "reviews", "آراء": "reviews",
                "creator": "creators", "مبدع": "creators", "إلهام": "creators", "الهام": "creators",
                "link": "links", "social": "links", "روابط": "links", "تواصل": "links",
                "contact": "contact", "اتصال": "contact",
            }
            found_keys = []
            for token in re.split(r'[,،\s\->]+', lower):
                token = token.strip()
                if not token:
                    continue
                for kw, skey in key_map.items():
                    if kw in token and skey not in found_keys:
                        found_keys.append(skey)
                        break
            if len(found_keys) >= 2:
                chosen_order = found_keys
                preset_name = "الترتيب المخصص" if is_ar else "Custom layout"

        if chosen_order is None:
            reply = (
                "يرجى اختيار أحد النماذج الجاهزة أو تحديد الأقسام المطلوبة:"
                if is_ar else
                "Please choose one of the quick presets or list your desired sections:"
            )
            quick = (
                ["مسؤول التوظيف أولاً", "العميل أولاً", "الإثبات الاجتماعي أولاً", "الافتراضي للثيم"]
                if is_ar else
                ["Recruiter first", "Client first", "Social proof first", "Theme default"]
            )
            return self._workflow_response(reply, quick + self._cancel_pill(is_ar))

        res = update_section_layout(self.user, section_order=chosen_order)
        self._clear_workflow()
        reply = (
            f"✅ تم تحديث ترتيب أقسام معرض أعمالك إلى **«{preset_name}»** بنجاح! ↕️"
            if is_ar else
            f"✅ Updated portfolio section order to **{preset_name}**! ↕️"
        )
        quick = (
            ["إضافة مشروع جديد", "إضافة تقييم عميل", "فحص معرض الأعمال"]
            if is_ar else
            ["Add a project", "Add a review", "Audit portfolio"]
        )
        return self._workflow_response(reply, quick, [res], res.get("snapshot_id"))

    # -- Entry point ----------------------------------------------------------

    def _handle_guided(self, user_text):
        """
        Handles deterministic multi-step wizards (add project, change theme, new bio, add review).
        Runs before any LLM call so the flows are identical in Groq and local modes.
        Returns a response dict, or None if the message isn't part of a guided flow.
        """
        is_ar = self.language == "ar"
        lower = (user_text or "").strip().lower()

        # Cancel any active wizard
        if self.conversation.workflow_state and any(
            w in lower for w in WORKFLOW_CANCEL_WORDS
        ):
            self._clear_workflow()
            reply = (
                "تم الإلغاء. هل هناك شيء آخر أساعدك به؟"
                if is_ar else
                "Cancelled. What else can I help with?"
            )
            return self._workflow_response(reply, [])

        # Advance an active wizard
        if self.conversation.workflow_state:
            state = self.conversation.workflow_state
            wtype = state.get("type")
            if wtype == "add_project":
                return self._advance_add_project(state, user_text)
            if wtype == "change_theme":
                return self._advance_change_theme(state, user_text)
            if wtype == "bio":
                return self._advance_bio(state, user_text)
            if wtype == "add_review":
                return self._advance_add_review(state, user_text)
            if wtype == "fix_project_url":
                return self._advance_fix_project_url(state, user_text)
            if wtype == "reorder_sections":
                return self._advance_reorder_sections(state, user_text)
            self._clear_workflow()

        # Start a new wizard
        intent = self._detect_guided_intent(user_text)
        if intent == "add_project":
            return self._start_add_project_workflow(user_text)
        if intent == "change_theme":
            return self._start_change_theme_workflow()
        if intent == "bio":
            return self._start_bio_workflow()
        if intent == "add_review":
            return self._start_add_review_workflow(user_text)
        if intent == "fix_project_url":
            return self._start_fix_project_url_workflow(user_text)
        if intent == "reorder_sections":
            return self._start_reorder_sections_workflow()

        return None

    # -----------------------------------------------------------------------
    # Fallback Dev Mode
    # -----------------------------------------------------------------------

    def _fallback_dev_response(self, user_text: str):
        """
        Intelligent Local Fallback Mode: executes real domain tools for standard
        requests even when a valid GROQ_API_KEY is not yet configured in .env.
        """
        is_ar = self.language == "ar"
        lower = user_text.lower().strip()
        executed_actions = []
        quick_replies = []
        snapshot_id = None

        key_tip = (
            "\n\n*(ملاحظة للمطور: لتفعيل الذكاء الاصطناعي التوليدي الكامل، يرجى وضع مفتاح Groq API صالح في ملف `.env`: `GROQ_API_KEY=gsk_...` من [Groq Console](https://console.groq.com))*"
            if is_ar else
            "\n\n*(Dev Note: Running in Smart Local Mode. To enable full AI reasoning, add your key to `.env`: `GROQ_API_KEY=gsk_...` from [Groq Console](https://console.groq.com))*"
        )

        # 1. Bio Requests
        if any(w in lower for w in ["bio", "نبذة", "نبذه", "headline", "title", "who i am"]):
            if is_ar:
                new_bio = "مونتير ومصمم بصري محترف بخبرة في إخراج ومونتاج الإعلانات التجارية عالية الجودة، وتصميم الصوت والتلوين السينمائي في DaVinci Resolve. أساعد العلامات التجارية وصناع المحتوى على تحويل أفكارهم إلى قصص بصرية ملهمة."
                new_title = "مونتير إعلانات وأفلام سينمائية"
            else:
                new_bio = "Commercial & Narrative Video Editor with extensive experience cutting dynamic brand campaigns, high-impact commercials, and documentary shorts. Expert in DaVinci Resolve color grading, pacing, and immersive sound design."
                new_title = "Commercial & Cinematic Video Editor"

            res = update_personal_info(self.user, bio=new_bio, title=new_title)
            executed_actions.append(res)
            snapshot_id = res.get("snapshot_id")
            reply = (
                f"تم تحديث النبذة والمسمى المهني بنجاح!{key_tip}"
                if is_ar else
                f"Updated your bio and headline!{key_tip}"
            )
            quick_replies, _ = self._next_best_actions()

        # 2. Skills Requests
        elif any(w in lower for w in ["skill", "مهارة", "مهارات", "davinci", "color grading", "resolve", "sound design", "tools"]):
            skills_to_add = ["DaVinci Resolve", "Color Grading", "Sound Design", "After Effects", "Premiere Pro"]
            res = manage_skills(self.user, add_skills=skills_to_add)
            executed_actions.append(res)
            snapshot_id = res.get("snapshot_id")
            reply = (
                f"تمت إضافة المهارات: {', '.join(skills_to_add)}.{key_tip}"
                if is_ar else
                f"Added skills: {', '.join(skills_to_add)}.{key_tip}"
            )
            quick_replies, _ = self._next_best_actions()

        # 3. Theme Requests
        elif any(w in lower for w in ["theme", "ثيم", "قالب", "cinematic", "minimal", "creative", "monochrome", "yellow", "cyan"]):
            target_theme = "minimal"
            if "cinematic" in lower or "سينمائي" in lower: target_theme = "cinematic"
            elif "creative" in lower or "إبداعي" in lower: target_theme = "creative"
            elif "yellow" in lower: target_theme = "yellow"
            elif "cyan" in lower: target_theme = "cyan"
            elif "monochrome" in lower: target_theme = "monochrome"

            res = change_theme(self.user, target_theme)
            if res.get("clarification_needed"):
                reply = res.get("question")
                quick_replies = res.get("quick_replies", [])
            else:
                executed_actions.append(res)
                snapshot_id = res.get("snapshot_id")
                reply = (
                    f"تم تغيير الثيم إلى '{target_theme}'.{key_tip}"
                    if is_ar else
                    f"Switched theme to '{target_theme}'.{key_tip}"
                )
                quick_replies, _ = self._next_best_actions()

        # 4. Project / Reel Requests
        elif any(w in lower for w in ["project", "reel", "video", "مشروع", "فيديو", "ريلز"]):
            import re
            urls = re.findall(r'https?://\S+', user_text)
            if urls:
                url = urls[0]
                title = user_text.replace(url, "").strip() or "Featured Video Project"
                is_reel = any(k in lower for k in ["reel", "short", "ريلز", "قصير"])
                v_type = "reel" if is_reel else "long"
                res = add_project(self.user, title=title, url=url, video_type=v_type, category_name="Featured Work")
                executed_actions.append(res)
                snapshot_id = res.get("snapshot_id")
                reply = (
                    f"تمت إضافة المشروع '{title}' بنجاح!{key_tip}"
                    if is_ar else
                    f"Added project '{title}' to your portfolio!{key_tip}"
                )
                quick_replies, _ = self._next_best_actions()
            else:
                reply = (
                    "أرسل رابط الفيديو (YouTube أو Vimeo) وعنوانه:"
                    if is_ar else
                    "Send the video URL (YouTube or Vimeo) and title:"
                )
                quick_replies = (
                    ["فيديو طويل (16:9)", "ريلز قصير (9:16)", "سأضع الرابط الآن"]
                    if is_ar else
                    ["Long video (16:9)", "Short reel (9:16)", "I'll paste the URL now"]
                )

        # 5. Audit & Recommendations Requests
        elif any(w in lower for w in ["audit", "review my portfolio", "recommend", "suggest", "improve", "فحص", "راجع", "مراجعة", "تحسين", "نصائح", "اقتراح"]):
            goal = "client"
            if any(w in lower for w in ["recruiter", "hire", "job", "وظيفة", "توظيف", "مقابلة"]):
                goal = "recruiter"
            elif any(w in lower for w in ["agency", "وكالة", "وكالات", "استوديو"]):
                goal = "agency"
            elif any(w in lower for w in ["creator", "influencer", "social", "youtube", "صانع محتوى", "يوتيوب", "سوشيال"]):
                goal = "creator"

            audit_res = audit_portfolio(self.user, goal=goal)
            audit = audit_res.get("audit", {})
            executed_actions.append(audit_res)
            score = audit.get("score", 0)
            strengths = audit.get("strengths", [])
            gaps = audit.get("gaps", [])
            theme_suggestion = audit.get("theme_suggestion")

            if is_ar:
                lines = [f"راجعت معرض أعمالك وفقاً لهدف «{goal}» وتقييمه **{score}/100**."]
                if strengths:
                    lines.append("\n**أبرز ما يميزك:**\n" + "\n".join(f"• {s}" for s in strengths[:3]))
                if gaps:
                    lines.append("\n**خطوات تحتاج للعناية:**\n" + "\n".join(
                        f"• **{g.get('ar_action', g['action'])}** — {g.get('ar_why', g['why'])}"
                        for g in gaps[:4]
                    ))
                if theme_suggestion:
                    reason = theme_suggestion.get("reason_ar", "")
                    lines.append(f"\nالثيم المقترح: **{theme_suggestion['name']}** — {reason}")
                reply = "\n".join(lines) + key_tip
            else:
                lines = [
                    f"I audited your portfolio against the **{goal}** goal — score **{score}/100**."
                ]
                if strengths:
                    lines.append("\n**What's working well:**\n" + "\n".join(f"• {s}" for s in strengths[:3]))
                if gaps:
                    lines.append("\n**Worth focusing on next:**\n" + "\n".join(
                        f"• **{g['action']}** — {g['why']}"
                        for g in gaps[:4]
                    ))
                if theme_suggestion:
                    reason = theme_suggestion.get("reason_en", "")
                    lines.append(f"\nTheme suggestion: **{theme_suggestion['name']}** — {reason}")
                reply = "\n".join(lines) + key_tip

            quick_replies, _ = self._next_best_actions()

        # 5.5 Experience / Education / Links / Visibility / Delete Requests
        elif any(w in lower for w in ["experience", "خبرة", "خبرات", "عمل", "وظيفة", "job", "worked at", "work at"]):
            if is_ar:
                reply = (
                    "ما هي وظيفتك واسم الشركة؟ (مثال: «مونتير أول في شركة XYZ»){key_tip}"
                )
            else:
                reply = (
                    "What is your job title and the company? (e.g. \"Senior Editor at Studio XYZ\"){key_tip}"
                )
            quick_replies, _ = self._next_best_actions()

        elif any(w in lower for w in ["education", "degree", "university", "school", "تعليم", "شهادة", "جامعة", "دراسة"]):
            if is_ar:
                reply = (
                    "ما اسم المؤسسة والدرجة العلمية؟ (مثال: «بكالوريوس إعلام من جامعة القاهرة»){key_tip}"
                )
            else:
                reply = (
                    "What institution and degree? (e.g. \"BA in Film from NYU\"){key_tip}"
                )
            quick_replies, _ = self._next_best_actions()

        elif any(w in lower for w in ["add link", "social", "instagram", "linkedin", "youtube link", "add link", "رابط", "روابط", "لينك", "سوشيال"]):
            urls = re.findall(r'https?://\S+', user_text)
            if urls:
                platform = "Instagram"
                if "linkedin" in lower:
                    platform = "LinkedIn"
                elif "youtube" in lower or "يوتيوب" in lower:
                    platform = "YouTube"
                elif "behance" in lower:
                    platform = "Behance"
                elif "vimeo" in lower:
                    platform = "Vimeo"
                res = add_link(self.user, platform=platform, url=urls[0])
                executed_actions.append(res)
                snapshot_id = res.get("snapshot_id")
                reply = (
                    f"تمت إضافة رابط {platform}!{key_tip}"
                    if is_ar else
                    f"Added your {platform} link!{key_tip}"
                )
                quick_replies, _ = self._next_best_actions()
            else:
                reply = (
                    "أرسل الرابط الذي تريد إضافته (Instagram أو LinkedIn أو YouTube...):"
                    if is_ar else
                    "Paste the link you want to add (Instagram, LinkedIn, YouTube...):"
                )
                quick_replies = (
                    ["Instagram", "LinkedIn", "YouTube", "Behance"]
                    if not is_ar else
                    ["إنستجرام", "لينكد إن", "يوتيوب", "بيهانس"]
                )

        elif any(w in lower for w in ["publish", "make public", "go live", "نشر", "انشر", "اجعل عام"]):
            res = set_portfolio_visibility(self.user, is_public=True)
            executed_actions.append(res)
            snapshot_id = res.get("snapshot_id")
            reply = (
                f"تم نشر معرض أعمالك! أصبح متاحاً الآن على رابطك.{key_tip}"
                if is_ar else
                f"Your portfolio is now public! It's live on your link.{key_tip}"
            )
            quick_replies, _ = self._next_best_actions()

        elif any(w in lower for w in ["make private", "hide", "private", "خاص", "إخفاء", "مخفي"]):
            res = set_portfolio_visibility(self.user, is_public=False)
            executed_actions.append(res)
            snapshot_id = res.get("snapshot_id")
            reply = (
                f"تم إخفاء معرض أعمالك.{key_tip}"
                if is_ar else
                f"Your portfolio is now private.{key_tip}"
            )
            quick_replies, _ = self._next_best_actions()

        # 6. Default General Guidance
        else:
            quick_replies, _ = self._next_best_actions()
            if is_ar:
                reply = (
                    f"مرحباً! أنا مساعد سكيليفلاي الذكي. كيف يمكنني مساعدتك في تطوير بورتفوليو أعمالك اليوم؟{key_tip}"
                )
            else:
                reply = (
                    f"Welcome! I am Skillifly AI. What would you like to update on your portfolio today?{key_tip}"
                )

        agent_msg = AgentMessage.objects.create(
            conversation=self.conversation,
            sender="agent",
            text=reply,
            actions_applied=executed_actions or None,
            quick_replies=quick_replies or None,
        )

        if snapshot_id:
            from core.models import PortfolioSnapshot
            PortfolioSnapshot.objects.filter(id=snapshot_id).update(message=agent_msg)

        return {
            "message": reply,
            "quick_replies": quick_replies,
            "actions": executed_actions,
            "snapshot_id": snapshot_id,
            "agent_message_id": agent_msg.id,
            "portfolio_state": get_portfolio_state(self.user),
        }

    # -----------------------------------------------------------------------
    # Proactive coaching: gap-aware next-step suggestions
    # -----------------------------------------------------------------------

    def _next_best_actions(self):
        """
        Deterministically suggests the most impactful next actions for the user,
        based on the portfolio's current health gaps. Returns quick-reply pills
        (localized) plus a one-line coaching hint the agent can append.
        """
        state = get_portfolio_state(self.user)
        pi = state.get("personal_info", {})
        projects = state.get("projects", [])
        skills = state.get("skills", [])
        reviews = state.get("reviews", [])
        experiences = state.get("experiences", [])
        links = state.get("links", [])
        account = state.get("account", {})

        bio = (pi.get("bio") or "").strip()
        has_bio = len(bio) > 30
        has_avatar = bool(account.get("has_profile_picture"))
        is_public = bool(account.get("is_public"))
        is_ar = self.language == "ar"

        # Ordered by impact (business->hiring funnel first, completion later).
        priorities = []
        if not has_bio:
            priorities.append(("bio", "Write a bio", "كتابة نبذة شخصية"))
        if not projects:
            priorities.append(("projects", "Add a project", "إضافة مشروع جديد"))
        if not skills:
            priorities.append(("skills", "Add skills", "إضافة مهارات"))
        if not reviews and (projects or experiences):
            priorities.append(("reviews", "Add a client review", "إضافة تقييم عميل"))
        if not experiences and not projects:
            priorities.append(("experience", "Add experience", "إضافة خبرة"))
        if not links:
            priorities.append(("links", "Add links", "إضافة روابط"))
        if not is_public:
            priorities.append(("visibility", "Publish portfolio", "نشر المعرض"))
        if not has_avatar:
            priorities.append(("avatar", "Add a photo", "إضافة صورة"))
        if not experiences and has_bio and projects:
            priorities.append(("experience", "Add experience", "إضافة خبرة"))
        if not reviews:
            priorities.append(("reviews", "Add a client review", "إضافة تقييم عميل"))

        # Keep the top 3 as quick replies; always keep one "audit/check" option.
        top = priorities[:3]
        pills = []
        for _key, en_label, ar_label in top:
            pills.append(ar_label if is_ar else en_label)
        pills.append("فحص معرض الأعمال" if is_ar else "Audit portfolio")

        # One-line coaching hint for the agent text.
        if top:
            _key, en_label, ar_label = top[0]
            hint = ar_label if is_ar else en_label
            hint_text = (
                f"الخطوة التالية المقترحة: {hint} — هذه أكبر فجوة في معرضك حالياً."
                if is_ar else
                f"Next best step: {hint} — it closes your biggest gap."
            )
        else:
            hint_text = (
                "معرض أعمالك شبه مكتمل! أستطيع فحصه وإعطائك تقييماً شاملاً."
                if is_ar else
                "Your portfolio is nearly complete — want me to audit it for a full score?"
            )

        return pills, hint_text

    # -----------------------------------------------------------------------
    # Second-pass reply refinement (grounded in actual tool results)
    # -----------------------------------------------------------------------

    def _refine_agent_reply(self, user_text, executed_actions, raw_content, clarification_question, hint_text=""):
        """
        After tool execution, runs one small LLM pass to craft a final, accurate
        1-2 sentence confirmation that is grounded in the REAL tool results
        (what actually changed) rather than the model's pre-execution text.
        Falls back cleanly to the raw content when the LLM is unavailable.
        """
        if not (self.client and not self.is_placeholder_key):
            return None
        if clarification_question or not executed_actions:
            return None

        is_ar = self.language == "ar"
        try:
            facts = []
            for a in executed_actions[:6]:
                msg = a.get("message", "")
                a_type = a.get("action_type", "")
                if a_type == "audit_portfolio":
                    audit = a.get("audit", {})
                    facts.append(
                        f"audit score={audit.get('score')} for goal '{audit.get('goal')}': "
                        f"strengths={audit.get('strengths', [])[:3]}; top actions={[g.get('action') for g in (audit.get('gaps') or [])[:3]]}"
                    )
                else:
                    facts.append(f"{a_type}: {msg}")
            # Include any 'diff' for more precise confirmations
            diffs = []
            for a in executed_actions[:6]:
                d = a.get("diff") or {}
                for field, change in d.items():
                    if isinstance(change, dict) and "old" in change and "new" in change:
                        diffs.append(f"{field}: '{change.get('old')}' -> '{change.get('new')}'")
            if diffs:
                facts.append("actual changes: " + " | ".join(diffs[:6]))

            system_prompt = (
                "You are Skillifly AI, an elite Creative Director confirming portfolio actions. "
                "Format your response EXACTLY like this:\n"
                "1. Start with ✅ followed by a confident, specific confirmation of what changed. "
                "**Bold** the key values (project titles, theme names, skill names, bio excerpts).\n"
                "2. If a suggested next step is provided and relevant, add it on a NEW LINE starting with 📌.\n"
                "3. Never mention tools, JSON, function names, or implementation details.\n"
                "4. Keep the tone warm but authoritative — like a Creative Director confirming a client brief.\n"
                "5. Never open with filler ('Certainly!', 'Sure thing!', 'Great!'). Open directly with ✅.\n"
                "6. Respond in the user's language. If the draft already reads well, improve its formatting only."
            )
            user_prompt = (
                f"User said: \"{user_text}\"\n"
                f"Confirmed results:\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n"
                f"Suggested impactful next step (use only if it fits, in the user's language): {hint_text or 'none'}\n"
                f"My draft confirmation (improve or keep): {raw_content or ''}"
            )
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=220,
            )
            refined = (response.choices[0].message.content or "").strip()
            if len(refined) > 5:
                return refined[:600]
        except Exception as e:
            logger.warning(f"Reply refinement failed: {e}")
        return None

    def _compose_grounded_reply(self, executed_actions, hint_text=""):
        """
        Last-resort fallback when no LLM confirmation is available: builds a
        clean, language-safe, data-backed reply from the tool results so the
        user always gets a smart summary even in the worst-case path.
        """
        if not executed_actions:
            return None
        is_ar = self.language == "ar"

        if is_ar:
            details = [
                (a.get("message") or "").strip().rstrip(".!?")
                for a in executed_actions[:5]
                if (a.get("message") or "").strip()
            ]
            if details:
                body = "✅ " + "\n• ".join(f"**{d}**" for d in details[:1])
                if len(details) > 1:
                    body += "\n" + "\n".join(f"• {d}" for d in details[1:])
            else:
                body = "✅ تم تنفيذ طلبك بنجاح — تم تحديث معرض أعمالك وحفظ نسخة احتياطية."
        else:
            details = [
                (a.get("message") or "").strip().rstrip(".!?")
                for a in executed_actions[:5]
                if (a.get("message") or "").strip()
            ]
            if not details:
                return None
            if len(details) == 1:
                body = f"✅ **{details[0]}.**"
            else:
                body = "✅ **Updates applied:**\n" + "\n".join(f"• {d}." for d in details)

        if hint_text and hint_text not in body:
            body = f"{body}\n\n📌 {hint_text}"
        return body[:700]

    # -----------------------------------------------------------------------
    # Dedicated LLM Audit Presentation (high analytical standards)
    # -----------------------------------------------------------------------

    def _present_audit_with_llm(self, audit_result, user_text):
        """
        Makes a dedicated LLM call to present audit findings with exceptional
        depth and alignment to the user's goal.  Returns the LLM-generated
        presentation or None when the LLM is unavailable / fails.
        """
        if not (self.client and not self.is_placeholder_key):
            return None

        is_ar = self.language == "ar"
        audit = audit_result.get("audit", {})
        goal = audit.get("goal", "client")

        audit_json = json.dumps(audit, ensure_ascii=False, indent=2)

        if is_ar:
            system_prompt = (
                "أنت مستشار بورتفوليو عالمي المستوى في Skillifly AI.\n"
                "لديك نتائج فحص كاملة للمستخدم. قدم تقريراً احترافياً مُنسّقاً.\n\n"
                f"هدف المستخدم: **{goal}**.\n\n"
                "معايير التنسيق والعرض (طبّقها حرفياً):\n"
                "1. ابدأ بسطر التقييم: «📊 **النتيجة: X/100** — جملة واحدة واثقة تربط النتيجة بهدفه».\n"
                "2. أضف قسم **نقاط القوة:** مع 2-3 نقاط، كل واحدة تبدأ بـ • وتحتوي على **عنوان بولد** ثم شرح موجز.\n"
                "3. أضف قسم **الأولويات:** مع 3-4 خطوات مرقّمة (1. 2. 3.). كل خطوة: **الإجراء بولد** — لماذا يهم لهدفه.\n"
                "4. إذا كان هناك اقتراح ثيم، أضفه في سطر مستقل يبدأ بـ 🎨.\n"
                "5. أنهِ بجملة تحفيزية واحدة.\n"
                "6. لا تذكر أي أدوات أو JSON أو تفاصيل تقنية.\n"
                "7. استخدم markdown: **بولد** للعناوين والقيم المهمة.\n"
                "8. ردّ بالعربية."
            )
        else:
            system_prompt = (
                "You are a world-class portfolio strategist at Skillifly AI.\n"
                "You have the user's full audit data. Present it as a professionally formatted briefing.\n\n"
                f"The user's goal: **{goal}**.\n\n"
                "Formatting standards (apply ALL of them precisely):\n"
                "1. Open with: «📊 **Score: X/100** — one confident sentence explaining what this means for their goal».\n"
                "2. Add a **Strengths:** section with 2-3 bullet points. Each: • **Bold label** followed by brief reasoning.\n"
                "3. Add a **Priorities:** section with 3-4 numbered items. Each: **Bold action** — why it matters for their goal.\n"
                "4. If there is a theme suggestion, add it on its own line starting with 🎨.\n"
                "5. Close with one motivating sentence.\n"
                "6. Do NOT mention tools, JSON, function names, or implementation details.\n"
                "7. Use markdown: **bold** for all key terms, section headers, values, and action items.\n"
                "8. Respond in the user's language."
            )

        user_prompt = (
            f"User said: \"{user_text}\"\n\n"
            f"Full audit data (use ALL of it — do not ignore strengths, gaps, recommendations, quick_wins, or theme_suggestion):\n"
            f"{audit_json}\n\n"
            "Present the audit to the user now with exceptional analytical depth and goal alignment."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.65,
                max_tokens=700,
            )
            result = (response.choices[0].message.content or "").strip()
            if len(result) > 30:
                return result[:1200]
        except Exception as e:
            logger.warning(f"Audit LLM presentation failed: {e}")
        return None

    # -----------------------------------------------------------------------
    # Main Entry Point
    # -----------------------------------------------------------------------

    def process_message(self, user_text: str):
        """
        Main entry point: receives user prompt, runs Groq function calling loop,
        executes portfolio tools, saves conversation history, and returns structured result.
        """
        user_text = (user_text or "").strip()
        if not user_text:
            return {"error": "Message cannot be empty."}

        # 1. Record User Message
        AgentMessage.objects.create(
            conversation=self.conversation,
            sender="user",
            text=user_text,
        )

        # 1b. Guided multi-step workflows (add project / change theme / new bio)
        guided_response = self._handle_guided(user_text)
        if guided_response is not None:
            return guided_response

        # 2. No valid key → Smart Dev Fallback
        if not self.client or self.is_placeholder_key:
            return self._fallback_dev_response(user_text)

        # 3. Build State & System Prompt
        portfolio_state = get_portfolio_state(self.user)
        system_prompt = _build_system_prompt(self.user, portfolio_state, self.language)

        # 4. Build Recent History (last 20 messages, OpenAI format, trimmed to fit context)
        history_msgs = list(self.conversation.messages.order_by("-created_at")[:20])[::-1]
        messages = [{"role": "system", "content": system_prompt}]
        for m in history_msgs:
            role = "user" if m.sender == "user" else "assistant"
            messages.append({"role": role, "content": m.text})

        try:
            # 5. Call Groq
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=GROQ_TOOLS,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=2048,
            )
        except Exception as e:
            err_str = str(e)
            logger.warning(f"Groq API error ({self.model_name}): {err_str}")

            if any(k in err_str for k in ("invalid_api_key", "Invalid API Key", "401", "authentication")):
                logger.warning("Invalid Groq API key — falling back to local dev mode.")
                return self._fallback_dev_response(user_text)

            # Fallback chain: try lighter models before giving up
            fallback_models = ["qwen/qwen3.6-27b", "llama-3.1-8b-instant"]
            for fb_model in fallback_models:
                try:
                    response = self.client.chat.completions.create(
                        model=fb_model,
                        messages=messages,
                        tools=GROQ_TOOLS,
                        tool_choice="auto",
                        temperature=0.7,
                        max_tokens=2048,
                    )
                    logger.info(f"Fallback succeeded on model: {fb_model}")
                    break
                except Exception as e2:
                    logger.warning(f"Fallback model {fb_model} also failed: {e2}")
                    continue
            else:
                return self._fallback_dev_response(user_text)

        # 6. Parse response & execute tool calls
        choice = response.choices[0]
        msg = choice.message

        executed_actions = []
        quick_replies = []
        snapshot_id = None
        clarification_question = None
        tool_calls_record = []
        tool_results_record = []

        if msg.tool_calls:
            for tc in msg.tool_calls:
                fname = tc.function.name
                try:
                    fargs = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    fargs = {}

                tool_calls_record.append({"name": fname, "args": fargs})

                if fname in TOOL_MAP:
                    tool_func = TOOL_MAP[fname]
                    try:
                        res = tool_func(self.user, **fargs)
                        tool_results_record.append({"name": fname, "result": res})

                        if res.get("clarification_needed"):
                            clarification_question = res.get("question")
                            quick_replies.extend(res.get("quick_replies", []))
                        else:
                            executed_actions.append(res)
                            if res.get("snapshot_id"):
                                snapshot_id = res["snapshot_id"]
                    except Exception as ex:
                        logger.error(f"Error executing tool {fname}: {ex}")
                        tool_results_record.append({"name": fname, "error": str(ex)})

        # 7. Formulate Agent Response Text
        agent_text = msg.content or ""

        # Proactive coaching signals computed ONCE (data-driven next best step).
        coaching_pills = []
        coaching_hint = ""
        last_action_type = executed_actions[-1].get("action_type", "") if executed_actions else ""
        if executed_actions and not clarification_question:
            coaching_pills, coaching_hint = self._next_best_actions()
            if "audit" in last_action_type:
                coaching_hint = ""

        # 7a. Audit: dedicated deep-analysis LLM presentation (bypasses refinement).
        skip_refinement = False
        if not clarification_question:
            audit_action = next(
                (a for a in executed_actions if a.get("action_type") == "audit_portfolio"), None
            )
            if audit_action:
                presented = self._present_audit_with_llm(audit_action, user_text)
                if presented:
                    agent_text = presented
                    skip_refinement = True

        # 7b. Non-audit: second-pass refinement grounded in actual tool results.
        if not skip_refinement:
            refined = self._refine_agent_reply(
                user_text, executed_actions, agent_text, clarification_question, coaching_hint
            )
            if refined:
                agent_text = refined

        if clarification_question:
            if not agent_text:
                agent_text = clarification_question
            elif clarification_question not in agent_text:
                agent_text = f"{agent_text}\n\n{clarification_question}"

        # If the model returned no meaningful confirmation, compose a grounded one.
        if (not agent_text or len(agent_text.strip()) < 20) and executed_actions:
            grounded = self._compose_grounded_reply(executed_actions, coaching_hint)
            if grounded:
                agent_text = grounded

        if not agent_text and executed_actions:
            summaries = [a.get("message", "Done.") for a in executed_actions]
            agent_text = " ".join(summaries)

        if not agent_text:
            agent_text = (
                "كيف يمكنني مساعدتك في تطوير معرض أعمالك اليوم؟"
                if self.language == "ar" else
                "How can I help you customize your portfolio today?"
            )

        # Proactive coaching: append a short gap-aware hint after real actions.
        if coaching_hint and agent_text and len(agent_text) < 300 and coaching_hint not in agent_text:
            agent_text = f"{agent_text.strip()} {coaching_hint}"

        # Context-aware starter & follow-up quick reply pills
        if not quick_replies:
            if coaching_pills:
                quick_replies = coaching_pills
            else:
                _pills, _hint = self._next_best_actions()
                quick_replies = _pills

        # 8. Record Agent Message
        agent_msg = AgentMessage.objects.create(
            conversation=self.conversation,
            sender="agent",
            text=agent_text,
            tool_calls=tool_calls_record or None,
            tool_results=tool_results_record or None,
            actions_applied=executed_actions or None,
            quick_replies=quick_replies or None,
        )

        if snapshot_id:
            from core.models import PortfolioSnapshot
            PortfolioSnapshot.objects.filter(id=snapshot_id).update(message=agent_msg)

        if self.conversation.messages.count() <= 2:
            short_title = user_text[:30] + ("..." if len(user_text) > 30 else "")
            self.conversation.title = short_title
            self.conversation.save(update_fields=["title"])

        return {
            "message": agent_text,
            "quick_replies": quick_replies,
            "actions": executed_actions,
            "snapshot_id": snapshot_id,
            "agent_message_id": agent_msg.id,
            "portfolio_state": get_portfolio_state(self.user),
        }

