"""
Skillifly AI — provider-agnostic text generation and grounded copy writing.

Provider order: Groq (primary) -> Google Gemini (fallback) -> deterministic templates.

Every writer is grounded in the user's real portfolio data (see ``portfolio_payload``)
so generated copy reflects actual skills, projects, and experience instead of
hallucinating. All providers are wrapped in try/except so a missing/invalid key
silently degrades to a high-quality template instead of breaking the UI.
"""

import json
import logging
import os
import re
from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_MODEL = None
GEMINI_MODEL = None

PLACEHOLDER_KEYS = (
    "your_gemini_api_key",
    "your_groq_api_key",
    "change-me",
    "placeholder",
    "none",
    "fake-key-for-test",
    "test",
    "",
)


def _is_placeholder_key(key):
    if not key:
        return True
    k = str(key).strip().lower()
    return (
        k in PLACEHOLDER_KEYS
        or k.startswith("your_")
        or len(k) < 12
    )


def _provider_key(name):
    env_name = ("GROQ_API_KEY" if name == "groq" else "GEMINI_API_KEY")
    return os.environ.get(env_name, "") or getattr(settings, env_name, "")


def generation_provider():
    """Returns 'groq', 'gemini', or None (whichever is usable first)."""
    if not _is_placeholder_key(_provider_key("groq")):
        return "groq"
    if not _is_placeholder_key(_provider_key("gemini")):
        return "gemini"
    return None


def _groq_model():
    return (
        os.environ.get("GROQ_AGENT_MODEL", "")
        or getattr(settings, "GROQ_AGENT_MODEL", "")
        or "llama-3.3-70b-versatile"
    )


def _gemini_model():
    return (
        os.environ.get("GEMINI_AGENT_MODEL", "")
        or getattr(settings, "GEMINI_AGENT_MODEL", "")
        or "gemini-2.0-flash"
    )


class GenerationService:
    """Thin wrapper around Groq/Gemini chat completion used by all AI writers."""

    def __init__(self, language="en"):
        self.language = language
        self.groq_key = _provider_key("groq")
        self.gemini_key = _provider_key("gemini")
        self._groq_client = None
        self._gemini_client = None

    @property
    def provider(self):
        return generation_provider()

    @property
    def can_generate(self):
        return self.provider is not None

    def _get_groq_client(self):
        if self._groq_client is None and not _is_placeholder_key(self.groq_key):
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.groq_key)
            except Exception as e:
                logger.error("Failed to create Groq client: %s", e)
        return self._groq_client

    def _get_gemini_client(self):
        if self._gemini_client is None and not _is_placeholder_key(self.gemini_key):
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=self.gemini_key)
            except Exception as e:
                logger.error("Failed to create Gemini client: %s", e)
        return self._gemini_client

    def _call_groq(self, system_prompt, user_prompt, temperature, max_tokens):
        client = self._get_groq_client()
        if client is None:
            return None
        response = client.chat.completions.create(
            model=_groq_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        return text.strip() or None

    def _call_gemini(self, system_prompt, user_prompt, temperature, max_tokens):
        client = self._get_gemini_client()
        if client is None:
            return None
        contents = f"{system_prompt}\n\n{user_prompt}"
        result = client.models.generate_content(
            model=_gemini_model(),
            contents=contents,
            config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        text = ""
        if hasattr(result, "text"):
            text = result.text or ""
        else:
            try:
                text = "".join(p.text or "" for p in result.candidates[0].content.parts)
            except Exception:
                text = ""
        return text.strip() or None

    def generate(self, system_prompt, user_prompt, temperature=0.7, max_tokens=900):
        """Returns generated text or None when no provider is available/fails."""
        order = ("groq", "gemini") if self.provider == "groq" else ("gemini", "groq")
        for name in order:
            if _is_placeholder_key(_provider_key(name)):
                continue
            try:
                if name == "groq":
                    text = self._call_groq(system_prompt, user_prompt, temperature, max_tokens)
                else:
                    text = self._call_gemini(system_prompt, user_prompt, temperature, max_tokens)
                if text:
                    return text
            except Exception as e:
                logger.warning("Generation failed on %s provider: %s", name, e)
        return None


# ---------------------------------------------------------------------------
# Grounded portfolio context
# ---------------------------------------------------------------------------

def portfolio_payload(user, include_details=True):
    """
    Builds a compact, grounded picture of the user's portfolio for prompt
    injection. Only data the user has actually entered — no invented facts.
    """
    from core.models import Profile, PersonalInfo, Skill, Project, Experience, Theme, Category

    profile = Profile.objects.filter(user=user).first()
    personal_info = PersonalInfo.objects.filter(user=user).first()

    theme = None
    if profile and profile.theme:
        theme = {
            "name": profile.theme.name,
            "category": profile.theme.category.name if profile.theme.category else "",
        }

    skills = list(Skill.objects.filter(user=user).values_list("name", flat=True))

    projects = []
    reel_count = 0
    for p in Project.objects.filter(user=user).select_related("category"):
        projects.append({
            "title": p.title,
            "video_type": p.video_type,
            "category": p.category.name if p.category else "",
            "details": p.details or "",
        })
        if p.video_type == "reel":
            reel_count += 1

    experiences = [
        {
            "title": e.title,
            "company": e.company,
            "still_working": e.still_working,
            "details": e.details or "",
        }
        for e in Experience.objects.filter(user=user)
    ]

    payload = {
        "full_name": personal_info.full_name if personal_info else user.username,
        "headline": personal_info.title if personal_info else "",
        "current_bio": (personal_info.bio if personal_info else ""
                        or (profile.bio if profile else "")),
        "theme": theme,
        "skills": skills,
        "projects": projects,
        "reels": reel_count,
        "long_videos": len(projects) - reel_count,
        "experiences": experiences,
    }

    if include_details:
        from core.models import Education, Link
        payload["education"] = [
            {"school": e.school, "degree": e.degree, "field": e.field}
            for e in Education.objects.filter(user=user)
        ]
        payload["links"] = [l.platform for l in Link.objects.filter(user=user)]

    return payload


# ---------------------------------------------------------------------------
# Deterministic template fallbacks (used when no valid LLM key is configured)
# ---------------------------------------------------------------------------

def _years_phrase(years, is_ar):
    if years:
        return f"+{years} سنوات" if is_ar else f"{years}+ years"
    return "سنوات" if is_ar else "years"


def bio_template_fallback(years, apps, specialty, extra, language="en"):
    """Same deterministic output as the legacy agent bio generator."""
    is_ar = language == "ar"
    years_str = _years_phrase(years, is_ar)
    apps_str = (
        (apps or "").strip().rstrip(".,")
        if apps
        else ("برامج المونتاج الاحترافية" if is_ar else "industry-standard editing software")
    )
    specialty = (specialty or "").strip().rstrip(".,")

    extra_sentence = ""
    if extra and not _is_dismissal(extra):
        extra_sentence = f" {extra.strip()}"

    if is_ar:
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", specialty))
        headline = (
            f"{specialty} مونتير"
            if (specialty and has_arabic)
            else (f"مونتير {specialty}" if specialty else "مونتير محترف")
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


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

CLICHE_PHRASES = (
    "passionate", "passionate about", "love editing", "loves editing",
    "i love", "i am a passionate", "مونتير شغوف", "احب المونتاج", "أحب المونتاج",
)


def _bio_from_payload(payload, is_ar):
    """Best-effort summary used to ground the LLM prompt (English canonical)."""
    bits = []
    headline = payload.get("headline") or ""
    if headline:
        bits.append(f"current headline: {headline}")
    if payload.get("skills"):
        bits.append("skills: " + ", ".join(payload["skills"]))
    if payload.get("projects"):
        cats = "categories: " + ", ".join(
            sorted({p["category"] for p in payload["projects"] if p["category"]})
        )
        if cats != "categories: ":
            bits.append(cats)
        bits.append(
            f"projects: {len(payload['projects'])} total "
            f"({payload['reels']} reels, {payload['long_videos']} long videos)"
        )
    if payload.get("experiences"):
        first = payload["experiences"][0]
        bits.append(f"roles like: {first['title']} at {first['company']}")
    return "; ".join(bits)


def write_bio(user, language="en", years=None, apps=None, specialty=None, extra=""):
    """
    Writes a compelling, portfolio-grounded bio.

    Uses the configured LLM provider when available and we have real data to
    ground on; otherwise falls back to the proven deterministic template.
    """
    is_ar = language == "ar"
    payload = portfolio_payload(user)
    service = GenerationService(language=language)

    grounded = _bio_from_payload(payload, is_ar)
    should_use_llm = service.can_generate and payload.get("projects")

    if should_use_llm:
        current_bio = (payload.get("current_bio") or "").strip()
        lang_directive = (
            "Write the bio in clean professional Arabic (Modern Standard Arabic, "
            "Egyptian-appropriate)." if is_ar else "Write the bio in polished English."
        )
        system_prompt = (
            "You are Skillifly AI, an elite Creative Director and portfolio copywriter for video editors. "
            "Write short (2-3 sentences), confident, high-converting bio copy with zero cliches like "
            "'passionate' or 'love editing'. Ground every claim ONLY in the facts provided. "
            + lang_directive
        )
        user_prompt = (
            f"Portfolio facts:\n{grounded}\n\n"
            f"User says: years={years or 'unknown'}, apps={apps or 'listed above'}, "
            f"specialty={specialty or 'general'}, extra= {(extra or 'none').strip() or 'none'}"
        )
        generated = service.generate(system_prompt, user_prompt, temperature=0.75, max_tokens=400)
        if generated:
            return generated.strip()

    return bio_template_fallback(years, apps, specialty, extra, language)


def write_project_details(user, project, language="en"):
    """
    Writes a one-line showcase blurb for a single project, grounded in the
    project's own data plus the user's skills.
    """
    from core.models import Project

    if not isinstance(project, Project):
        project = Project.objects.filter(user=user, id=getattr(project, "id", project or 0)).first()
    if project is None:
        return ""

    is_ar = language == "ar"
    payload = portfolio_payload(user, include_details=False)
    service = GenerationService(language=language)

    category = project.category.name if project.category_id else ""
    video_type = "reel (vertical short)" if project.video_type == "reel" else "long (16:9 widescreen)"
    existing = (project.details or "").strip()

    if service.can_generate and (category or payload.get("skills")):
        skills = ", ".join(payload.get("skills", [])[:4])
        system_prompt = (
            "You are Skillifly AI, a creative portfolio copywriter. Write ONE punchy sentence "
            "(1 sentence, under 30 words) describing this video project for a video editor's "
            "portfolio. Ground it in the facts provided, mention the format and genre, and never "
            "invent claims. "
            + ("Output in professional Arabic." if is_ar else "Output in polished English.")
        )
        user_prompt = (
            f"Project title: {project.title}\nGenre: {category or 'video project'}\n"
            f"Format: {video_type}\nEditor skills: {skills or 'not listed'}"
            + (f"\nExisting notes: {existing}" if existing else "")
        )
        generated = service.generate(system_prompt, user_prompt, temperature=0.7, max_tokens=120)
        if generated:
            return generated.strip().strip('"')

    if is_ar:
        genre = category or "فيديو"
        suffix = "ريلز عمودي (9:16)" if project.video_type == "reel" else "فيديو طويل (16:9)"
        return f"{genre} — {suffix}: {project.title}"
    suffix = "vertical reel (9:16)" if project.video_type == "reel" else "long-form video (16:9)"
    return f"{category or 'Video project'} — {suffix} that showcases {project.title}."