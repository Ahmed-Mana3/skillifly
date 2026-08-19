from django.urls import path
from school import views

urlpatterns = [
    path('school/<slug:school_slug>/', views.school_home, name='school_home'),
    path('school/<slug:school_slug>/students/', views.school_students, name='school_students'),
    path('school/<slug:school_slug>/videos/', views.school_videos, name='school_videos'),
    path('school/<slug:school_slug>/videos/<int:pk>/rate/', views.rate_school_video, name='rate_school_video'),
    path('school/<slug:school_slug>/videos/<int:pk>/comment/', views.comment_school_video, name='comment_school_video'),
    path('school/<slug:school_slug>/students/<str:username>/rate/', views.rate_school_student, name='rate_school_student'),
    path('school/<slug:school_slug>/students/<str:username>/', views.school_student_detail, name='school_student_detail'),
    path('school/<slug:school_slug>/videos/<int:pk>/', views.school_video_detail, name='school_video_detail'),
]
