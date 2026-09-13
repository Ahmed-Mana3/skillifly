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
    lang_directive = (
        "### Language & Cultural Directive:\n"
        "- The user is interacting in Arabic.\n"
        "- Respond in natural, professional, and direct Arabic (Egyptian dialect mixed with clean Modern Standard Arabic where appropriate).\n"
        "- STRICT BREVITY: Keep all responses SHORT, CLEAR, and DIRECT TO THE POINT (1-2 sentences maximum).\n"
        "- Maintain industry terminology commonly used in the Arabic creative industry (e.g., مونتاج, كلر جريدنج, إعلانات تجارية, ريلز, تريلر, موشن جرافيكس).\n"
        "- All quick-reply pills, clarifying questions, and action summaries must be written in concise, fluent Arabic."
        if is_ar else
        "### Language Directive:\n"
        "- The user is interacting in English.\n"
        "- Respond in polished, confident, and direct English with industry-savvy creative agency terminology.\n"
        "- STRICT BREVITY: Keep all responses SHORT, CLEAR, and DIRECT TO THE POINT (1-2 sentences maximum)."
    )

    state_json = json.dumps(portfolio_state, indent=2, ensure_ascii=False)

    return f"""You are Skillifly AI — an elite Creative Director, Post-Production Producer, and Portfolio Architect built directly into Skillifly.
Your mission is to help video editors, colorists, motion designers, and filmmakers build a world-class, client-winning portfolio that lands high-ticket brand deals and agency contracts.

{lang_directive}

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

### 5. Plans, Custom Domains, PDF Resumes & Analytics:
- **Free Plan**: Unlimited video showcases, standard themes, hosted at `skillifly.cloud/<username>`.
- **Pro Monthly (99 EGP / 30 days)**: All themes unlocked, custom project categories, analytics dashboard.
- **Pro Annual (449 EGP / 365 days)**: Everything in Pro + **Custom Domain Connection** (e.g. `yourname.film` with automatic Let's Encrypt SSL) + **One-Click PDF Portfolio Export** (Playwright-generated high-res PDF resume for agency pitches).
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
5. **Post-Action Conciseness**: After invoking tools, provide a 1-sentence confirmation of what was updated.
6. **Smart & Generic Recommendations**:
   - When suggesting next actions or quick replies, ALWAYS keep them GENERIC and ACTION-ORIENTED (e.g. "Change the theme", "Add a project", "Write a bio", "Add skills", "Add a client review", "Audit portfolio").
   - NEVER tell the user to change to a specific theme (e.g. do NOT say "Change theme to Cinematic", say "Change the theme").
   - Base all portfolio audit recommendations strictly on what is genuinely missing in `portfolio_state`.
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

        self.model_name = getattr(settings, "GROQ_AGENT_MODEL", "qwen/qwen3.8-27b")

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
                f"تمت إضافة المشروع «{state.get('title')}» إلى معرض أعمالك بنجاح! 🎉"
                if is_ar else
                f"Added \"{state.get('title')}\" to your portfolio! 🎉"
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
                f"تم تحديث رابط «{project_title}» بنجاح! ✅"
                if is_ar else
                f'Link updated for "{project_title}"! ✅'
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
            f"تم تغيير الثيم إلى «{theme_name}» بنجاح! 🎨"
            if is_ar else
            f"Switched your portfolio to the **{theme_name}** theme! 🎨"
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

    def _generate_bio(self, years, apps, specialty, extra):
        is_ar = self.language == "ar"
        years_str = self._years_phrase(years, is_ar)
        apps_str = (
            (apps or "").strip().rstrip('.,')
            if apps
            else ("برامج المونتاج الاحترافية" if is_ar else "industry-standard editing software")
        )
        specialty = (specialty or "").strip().rstrip('.,')

        extra_sentence = ""
        if extra and not self._is_dismissal(extra):
            extra_clean = extra.strip()
            if is_ar:
                extra_sentence = f" {extra_clean}"
            else:
                extra_sentence = " " + extra_clean

        if is_ar:
            has_arabic = bool(re.search(r'[\u0600-\u06FF]', specialty))
            headline = f"{specialty} مونتير" if (specialty and has_arabic) else (
                f"مونتير {specialty}" if specialty else "مونتير محترف"
            )
            core = (
                f"{headline} بخبرة {years_str} في تحويل اللقطات الخام إلى قصص بصرية مؤثرة. "
                f"أتقن العمل على {apps_str}، وأمزج بين إيقاع مونتاج دقيق، وتلوين سينمائي غامر، "
                f"وتصميم صوتي احترافي لإنتاج محتوى يحقق نتائج حقيقية — من ريلز عالية التفاعل "
                f"إلى إعلانات تجارية متقنة."
            )
        else:
            headline = f"{specialty.title()} Video Editor" if specialty else "Video Editor"
            core = (
                f"{headline} with {years_str} of hands-on experience turning raw footage into "
                f"emotionally resonant stories. Proficient in {apps_str}, I blend tight pacing, "
                f"cinematic color grading, and immersive sound design to create content that "
                f"performs — from high-retention reels to polished brand commercials."
            )

        return f"{core}{extra_sentence}"

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
            bio = self._generate_bio(
                years=state.get("years"),
                apps=state.get("apps", ""),
                specialty=state.get("specialty", ""),
                extra=extra,
            )
            res = update_personal_info(self.user, bio=bio)
            self._clear_workflow()
            reply = (
                f"تم تحديث النبذة بنجاح! ✍️\n\n\"{bio}\""
                if is_ar else
                f"Updated your bio! ✍️\n\n\"{bio}\""
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
                f"تمت إضافة التقييم! {stars_str}\n\n**{client_name}**{title_part}\n\"{content}\""
                if is_ar else
                f"Review added! {stars_str}\n\n**{client_name}**{title_part}\n\"{content}\""
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
            f"تم تحديث ترتيب أقسام معرض أعمالك إلى «{preset_name}» بنجاح! ↕️"
            if is_ar else
            f"Updated portfolio section order to **{preset_name}**! ↕️"
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
                new_bio = "Passionate Commercial & Narrative Video Editor with extensive experience cutting dynamic brand campaigns, high-impact commercials, and documentary shorts. Expert in DaVinci Resolve color grading, pacing, and immersive sound design."
                new_title = "Commercial & Cinematic Video Editor"

            res = update_personal_info(self.user, bio=new_bio, title=new_title)
            executed_actions.append(res)
            snapshot_id = res.get("snapshot_id")
            reply = (
                f"تم تحديث النبذة والمسمى المهني بنجاح!{key_tip}"
                if is_ar else
                f"Updated your bio and headline!{key_tip}"
            )
            quick_replies = [
                "إضافة مهارات",
                "تغيير الثيم",
                "إضافة مشروع جديد",
            ] if is_ar else [
                "Add skills",
                "Change the theme",
                "Add a project",
            ]

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
            quick_replies = [
                "كتابة نبذة شخصية",
                "تغيير الثيم",
                "إضافة مشروع جديد",
            ] if is_ar else [
                "Write a bio",
                "Change the theme",
                "Add a project",
            ]

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
                quick_replies = [
                    "إضافة مشروع جديد",
                    "كتابة نبذة شخصية",
                    "فحص معرض الأعمال",
                ] if is_ar else [
                    "Add a project",
                    "Write a bio",
                    "Audit portfolio",
                ]

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
                quick_replies = [
                    "إضافة مشروع جديد",
                    "تغيير الثيم",
                    "إضافة تقييم عميل",
                ] if is_ar else [
                    "Add another project",
                    "Change the theme",
                    "Add a client review",
                ]
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
            state = get_portfolio_state(self.user)
            pi = state.get("personal_info", {})
            projs = state.get("projects", [])
            skills = state.get("skills", [])
            reviews = state.get("reviews", [])
            theme = state.get("theme", {}).get("name", "Default")

            missing = []
            if not pi.get("bio") or len(pi.get("bio", "")) < 30:
                missing.append("نبذة احترافية" if is_ar else "a detailed bio")
            if len(projs) == 0:
                missing.append("مشاريع فيديو" if is_ar else "video projects")
            if len(skills) == 0:
                missing.append("مهارات فنية" if is_ar else "skills")
            if len(reviews) == 0:
                missing.append("تقييمات عملاء" if is_ar else "client reviews")

            if missing:
                missing_str = "، و".join(missing[:2]) if is_ar else " and ".join(missing[:2])
                reply = (
                    f"راجعت معرض أعمالك: ينقصه {missing_str}. أنصحك بالبدء بإضافتها لزيادة جاذبية ملفك!{key_tip}"
                    if is_ar else
                    f"I reviewed your portfolio: you are currently missing {missing_str}. Adding these will make your portfolio much more credible!{key_tip}"
                )
            else:
                reply = (
                    f"معرض أعمالك مكتمل بشكل رائع ويحتوي على {len(projs)} مشاريع و{len(skills)} مهارات بثيم {theme}!{key_tip}"
                    if is_ar else
                    f"Your portfolio looks solid with {len(projs)} projects and {len(skills)} skills on the {theme} theme!{key_tip}"
                )

            quick_replies = [
                "إضافة مشروع جديد",
                "كتابة نبذة شخصية",
                "إضافة مهارات",
                "تغيير الثيم",
            ] if is_ar else [
                "Add a project",
                "Write a bio",
                "Add skills",
                "Change the theme",
            ]

        # 6. Default General Guidance
        else:
            if is_ar:
                reply = (
                    f"مرحباً! أنا مساعد سكيليفلاي الذكي. كيف يمكنني مساعدتك في تطوير بورتفوليو أعمالك اليوم؟{key_tip}"
                )
                quick_replies = [
                    "كتابة نبذة شخصية",
                    "إضافة مهارات",
                    "إضافة مشروع جديد",
                    "إضافة تقييم عميل",
                    "ترتيب أقسام المعرض",
                    "فحص معرض الأعمال",
                ]
            else:
                reply = (
                    f"Welcome! I am Skillifly AI. What would you like to update on your portfolio today?{key_tip}"
                )
                quick_replies = [
                    "Write a bio",
                    "Add skills",
                    "Add a project",
                    "Add a client review",
                    "Change sections order",
                    "Audit portfolio",
                ]

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
            "portfolio_state": get_portfolio_state(self.user),
        }

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

        # 4. Build Recent History (last 10 messages, OpenAI format)
        history_msgs = list(self.conversation.messages.order_by("-created_at")[:10])[::-1]
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

            # Try a lighter fallback model
            try:
                response = self.client.chat.completions.create(
                    model="qwen/qwen3.6-27b",
                    messages=messages,
                    tools=GROQ_TOOLS,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=2048,
                )
            except Exception as e2:
                logger.error(f"Groq fallback model also failed: {e2}")
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

        if clarification_question:
            if not agent_text:
                agent_text = clarification_question
            elif clarification_question not in agent_text:
                agent_text = f"{agent_text}\n\n{clarification_question}"

        if not agent_text and executed_actions:
            summaries = [a.get("message", "Done.") for a in executed_actions]
            agent_text = " ".join(summaries)

        if not agent_text:
            agent_text = (
                "كيف يمكنني مساعدتك في تطوير معرض أعمالك اليوم؟"
                if self.language == "ar" else
                "How can I help you customize your portfolio today?"
            )

        # Context-aware starter & follow-up quick reply pills
        if not quick_replies:
            is_ar = self.language == "ar"
            if executed_actions:
                first_type = executed_actions[0].get("action_type", "")
                if "personal_info" in first_type:
                    quick_replies = [
                        "إضافة مهارات",
                        "تغيير الثيم",
                        "إضافة مشروع جديد",
                    ] if is_ar else [
                        "Add skills",
                        "Change the theme",
                        "Add a project",
                    ]
                elif "skills" in first_type:
                    quick_replies = [
                        "كتابة نبذة شخصية",
                        "تغيير الثيم",
                        "إضافة تقييم عميل",
                    ] if is_ar else [
                        "Write a bio",
                        "Change the theme",
                        "Add a client review",
                    ]
                elif "theme" in first_type:
                    quick_replies = [
                        "إضافة مشروع جديد",
                        "كتابة نبذة شخصية",
                        "فحص معرض الأعمال",
                    ] if is_ar else [
                        "Add a project",
                        "Write a bio",
                        "Audit portfolio",
                    ]
                elif "project" in first_type:
                    quick_replies = [
                        "إضافة مشروع جديد",
                        "تغيير الثيم",
                        "إضافة تقييم عميل",
                    ] if is_ar else [
                        "Add another project",
                        "Change the theme",
                        "Add a client review",
                    ]
                elif "review" in first_type:
                    quick_replies = [
                        "إضافة مشروع جديد",
                        "تغيير الثيم",
                        "فحص معرض الأعمال",
                    ] if is_ar else [
                        "Add a project",
                        "Change the theme",
                        "Audit portfolio",
                    ]
                else:
                    quick_replies = [
                        "كتابة نبذة شخصية",
                        "إضافة مهارات",
                        "تغيير الثيم",
                        "إضافة مشروع جديد",
                    ] if is_ar else [
                        "Write a bio",
                        "Add skills",
                        "Change the theme",
                        "Add a project",
                    ]
            elif self.conversation.messages.count() <= 2:
                quick_replies = [
                    "كتابة نبذة شخصية",
                    "إضافة مهارات",
                    "تغيير الثيم",
                    "إضافة مشروع جديد",
                    "إضافة تقييم عميل",
                    "فحص معرض الأعمال",
                ] if is_ar else [
                    "Write a bio",
                    "Add skills",
                    "Change the theme",
                    "Add a project",
                    "Add a client review",
                    "Audit portfolio",
                ]

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
            "portfolio_state": get_portfolio_state(self.user),
        }

