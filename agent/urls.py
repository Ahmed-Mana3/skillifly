from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.chat_view, name='agent_chat'),
    path('history/', views.history_view, name='agent_history'),
    path('clear/', views.clear_view, name='agent_clear'),
    path('undo/<int:snapshot_id>/', views.undo_view, name='agent_undo'),
    path('feedback/', views.feedback_view, name='agent_feedback'),
]
