"""
HTTP endpoints for Skillifly AI.
Handles user chat requests, conversation history, fresh chat resets, and one-click undo.
"""

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.utils.translation import get_language

from core.models import AgentConversation, AgentMessage, PortfolioSnapshot
from agent.services import AgentService
from agent.tools import restore_snapshot, get_portfolio_state


@login_required
@require_POST
def chat_view(request):
    """
    Main chat endpoint: handles user prompt and returns agent response,
    clarifying questions, executed actions, and updated portfolio state.
    """
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except Exception:
        data = request.POST

    message = data.get("message", "").strip()
    if not message:
        return JsonResponse({"error": "Message is required."}, status=400)

    # Detect language: from payload, URL path /ar/, or cookie
    lang = data.get("language")
    if not lang:
        cookie_lang = request.COOKIES.get("skillifly_lang", "")
        path_is_ar = request.path.startswith("/ar/") or "/ar/" in request.META.get("HTTP_REFERER", "")
        lang = "ar" if (cookie_lang == "ar" or path_is_ar) else "en"

    service = AgentService(user=request.user, language=lang)
    result = service.process_message(message)

    return JsonResponse({
        "success": True,
        "data": result,
    })


@login_required
@require_GET
def history_view(request):
    """
    Returns messages from the current active conversation.
    """
    conversation = AgentConversation.objects.filter(
        user=request.user,
        is_active=True,
    ).first()

    if not conversation:
        return JsonResponse({
            "conversation_id": None,
            "messages": [],
            "portfolio_state": get_portfolio_state(request.user),
        })

    messages_data = []
    for m in conversation.messages.order_by("created_at"):
        messages_data.append({
            "id": m.id,
            "sender": m.sender,
            "text": m.text,
            "actions": m.actions_applied or [],
            "quick_replies": m.quick_replies or [],
            "created_at": m.created_at.strftime("%H:%M"),
        })

    return JsonResponse({
        "conversation_id": conversation.id,
        "title": conversation.title,
        "messages": messages_data,
        "portfolio_state": get_portfolio_state(request.user),
    })


@login_required
@require_POST
def clear_view(request):
    """
    Marks the current conversation as inactive and starts a fresh one.
    """
    AgentConversation.objects.filter(user=request.user, is_active=True).update(is_active=False)
    new_conv = AgentConversation.objects.create(user=request.user, is_active=True)

    return JsonResponse({
        "success": True,
        "message": "Conversation reset.",
        "conversation_id": new_conv.id,
    })


@login_required
@require_POST
def undo_view(request, snapshot_id):
    """
    Reverts portfolio changes to a previous snapshot state.
    """
    try:
        res = restore_snapshot(user=request.user, snapshot_id=int(snapshot_id))
        res["portfolio_state"] = get_portfolio_state(request.user)
        return JsonResponse(res)
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e),
        }, status=400)
