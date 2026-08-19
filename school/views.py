from decimal import Decimal, ROUND_HALF_UP
import re
import struct
import urllib.request

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from core.models import School, SchoolStudent, Project, SchoolVideoRating, SchoolStudentRating, SchoolVideoComment, UserPayment, ManualPayment


def _get_school(request, school_slug):
    return get_object_or_404(School, slug=school_slug)


def _round1(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def _school_students(school):
    return SchoolStudent.objects.filter(school=school).select_related('user')


def _school_projects(school):
    students = _school_students(school)
    user_ids = [s.user_id for s in students if s.user_id]
    if not user_ids:
        return Project.objects.none(), {}
    by_user = {s.user_id: s for s in students if s.user_id}
    return Project.objects.filter(user_id__in=user_ids).select_related('user'), by_user


def _project_color(project, student):
    if student:
        return student.avatar_color
    palette = ["#1D4ED8", "#6D28D9", "#059669", "#DC2626", "#334155", "#0EA5E9", "#B45309", "#BE185D"]
    return palette[(project.pk or 0) % len(palette)]


_DRIVE_FILE_RE = re.compile(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([A-Za-z0-9_-]+)')


def _drive_stream_url(url):
    """Return a streaming URL for a Google Drive file, or None."""
    if not url:
        return None
    m = _DRIVE_FILE_RE.search(url)
    if not m:
        m = re.search(r'[?&]id=([A-Za-z0-9_-]+)', url)
    if not m:
        return None
    return f'https://drive.google.com/uc?export=view&id={m.group(1)}'


_VIDEO_CODECS = (b'avc1', b'avc3', b'hvc1', b'hev1', b'vp08', b'vp09', b'av01', b'mp4v', b'encv')


def _fetch_chunk(url, start, end, timeout=20):
    headers = {'User-Agent': 'Mozilla/5.0', 'Range': f'bytes={start}-{end}'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get('Content-Type') or ''
            total = int(r.headers.get('Content-Length') or 0)
            data = r.read(end - start + 1 + 2048)
        return data, ct, total
    except Exception:
        return b'', '', 0


def _mp4_dims_from_drive(url):
    """Probe a Drive video's real codec dimensions by reading its stsd box."""
    stream_url = _drive_stream_url(url)
    if not stream_url:
        return None
    head, ct, total = _fetch_chunk(stream_url, 0, 4096, timeout=15)
    if not head or ct.split(';')[0].strip() not in ('video/mp4', 'application/octet-stream', 'video/quicktime'):
        return None
    if not total:
        return None
    chunk, _, _ = _fetch_chunk(stream_url, 0, 2 * 1024 * 1024 - 1)
    if not chunk:
        return None
    moov = _mp4_find_box(chunk, b'moov')
    if not moov:
        tail, _, _ = _fetch_chunk(stream_url, max(0, total - 2 * 1024 * 1024), total - 1)
        if not tail:
            return None
        chunk = tail
        moov = _mp4_find_box(chunk, b'moov')
    if not moov:
        return None
    s, size = moov
    return _mp4_dims_in_moov(chunk, s, size)


def _mp4_find_box(data, name):
    i = 0
    while True:
        i = data.find(name, i)
        if i < 0:
            return None
        s = i - 4
        if s >= 0:
            size = struct.unpack('>I', data[s:s + 4])[0]
            if 8 <= size <= len(data) - s:
                return s, size
        i += 4


def _mp4_walk(data, start, end, name):
    out = []
    i = start
    while i + 8 <= end:
        size = struct.unpack('>I', data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        hdr = 8
        if size == 1:
            if i + 16 > end:
                break
            size = struct.unpack('>Q', data[i + 8:i + 16])[0]
            hdr = 16
        if size == 0:
            break
        if typ == name:
            out.append((i, size, hdr))
        if size < hdr:
            break
        i += size
    return out


def _mp4_dims_in_moov(data, s, size):
    end = min(len(data), s + size)
    for ti, ts, th in _mp4_walk(data, s + 8, end, b'trak'):
        for ki, ks, kh in _mp4_walk(data, ti + th, min(len(data), ti + ts), b'mdia'):
            for mi, ms, mh in _mp4_walk(data, ki + kh, min(len(data), ki + ks), b'minf'):
                for ni, ns, nh in _mp4_walk(data, mi + mh, min(len(data), mi + ms), b'stbl'):
                    for bi, bs, bh in _mp4_walk(data, ni + nh, min(len(data), ni + ns), b'stsd'):
                        if bi + 16 > len(data):
                            continue
                        cnt = struct.unpack('>I', data[bi + 12:bi + 16])[0]
                        en = bi + 16
                        for _ in range(cnt or 1):
                            if en + 36 > len(data):
                                break
                            es = struct.unpack('>I', data[en:en + 4])[0]
                            etyp = data[en + 4:en + 8]
                            if etyp in _VIDEO_CODECS:
                                w = struct.unpack('>H', data[en + 32:en + 34])[0]
                                h = struct.unpack('>H', data[en + 34:en + 36])[0]
                                if w and h:
                                    return w, h
                            if es < 8:
                                break
                            en += es
    return None


def _attach_media_dims(video):
    """Ensure Drive reels have cached real dimensions; set video.landscape."""
    video.landscape = False
    if video.video_type != 'reel':
        return
    if not video.media_width or not video.media_height:
        dims = _mp4_dims_from_drive(video.url)
        if dims:
            video.media_width, video.media_height = dims
            Project.objects.filter(pk=video.pk).update(media_width=dims[0], media_height=dims[1])
    video.landscape = bool(video.media_width and video.media_height and video.media_width > video.media_height)


def school_home(request, school_slug):
    school = _get_school(request, school_slug)
    projects, _ = _school_projects(school)
    students_count = _school_students(school).count()
    videos_count = projects.count()
    avg_rating = projects.aggregate(a=Avg('school_video_ratings__value'))['a']

    code = school.discount_code
    fawaterk_count = UserPayment.objects.filter(
        discount_code_used__iexact=code,
        status='paid',
        subscription__days=365,
    ).count()
    manual_count = ManualPayment.objects.filter(
        discount_code_used__iexact=code,
        status='verified',
        plan_type='pro_annual',
    ).count()
    revenue_egp = (fawaterk_count + manual_count) * 100

    return render(request, 'school/school_page.html', {
        'school': school,
        'students_count': students_count,
        'videos_count': videos_count,
        'avg_rating': _round1(avg_rating),
        'revenue_egp': revenue_egp,
    })


def _star_fills(avg):
    """Return a list of 5 percentages (0-100) for star fill based on a 0-5 average."""
    avg = float(avg or 0)
    return [int(min(1, max(0, avg - i)) * 100) for i in range(5)]


def school_students(request, school_slug):
    school = _get_school(request, school_slug)
    
    # Search parameter
    search_query = request.GET.get('search', '').strip()
    
    # Sort parameter
    sort_by = request.GET.get('sort', 'rating_high')
    
    qs = SchoolStudent.objects.filter(school=school).annotate(
        rating_avg=Avg('ratings__value'),
        rating_count=Count('ratings'),
        video_rating_avg=Avg('user__projects__school_video_ratings__value'),
        video_rating_count=Count('user__projects__school_video_ratings', distinct=True),
    )
    
    # Apply search filter
    if search_query:
        qs = qs.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__personal_info__full_name__icontains=search_query) |
            Q(user__personal_info__title__icontains=search_query)
        )
    
    # Apply ordering
    if sort_by == 'rating_high':
        qs = qs.order_by('-video_rating_avg', 'order', 'id')
    elif sort_by == 'rating_low':
        qs = qs.order_by('video_rating_avg', 'order', 'id')
    elif sort_by == 'name_asc':
        qs = qs.order_by('user__first_name', 'user__last_name', 'id')
    elif sort_by == 'name_desc':
        qs = qs.order_by('-user__first_name', '-user__last_name', 'id')
    else:
        qs = qs.order_by('-video_rating_avg', 'order', 'id')
    
    hidden_count = qs.filter(is_hidden=True).count()
    students = list(qs)
    for s in students:
        s.star_fills = _star_fills(s.video_rating_avg)
    
    return render(request, 'school/students_list.html', {
        'school': school,
        'students': students,
        'hidden_count': hidden_count,
        'search_query': search_query,
        'sort_by': sort_by,
    })


def school_student_detail(request, school_slug, username):
    school = _get_school(request, school_slug)
    student = get_object_or_404(SchoolStudent, school=school, user__username=username)
    student.video_count = student.user.projects.count() if student.user_id else 0
    student.reel_count = 0
    student.avg_rating = _round1(
        student.user.projects.aggregate(a=Avg('school_video_ratings__value'))['a']
    ) if student.user_id else None
    videos = student.user.projects.all() if student.user_id else Project.objects.none()
    for video in videos:
        video.color = _project_color(video, student)
    return render(request, 'school/student_detail.html', {
        'school': school,
        'student': student,
        'videos': videos,
    })


def school_videos(request, school_slug):
    school = _get_school(request, school_slug)
    projects, by_user = _school_projects(school)
    videos = (
        projects
        .annotate(rating_avg=Avg('school_video_ratings__value'), rating_count=Count('school_video_ratings'))
        .filter(rating_count=0)
        .order_by('-id')
    )
    for video in videos:
        student = by_user.get(video.user_id)
        video.student = student
        video.color = _project_color(video, student)
        video.avg_rating = _round1(video.rating_avg)
        video.comments_list = list(video.school_video_comments.select_related().order_by('-created_at')[:5])
    return render(request, 'school/videos_list.html', {
        'school': school,
        'videos': videos,
    })


def school_video_detail(request, school_slug, pk):
    school = _get_school(request, school_slug)
    projects, by_user = _school_projects(school)

    student_username = request.GET.get('student')
    student_filter = None
    if student_username:
        ss = SchoolStudent.objects.filter(school=school, user__username__iexact=student_username).first()
        if ss:
            student_filter = by_user.get(ss.user_id)

    video = get_object_or_404(projects, pk=pk)
    student = by_user.get(video.user_id)
    video.student = student
    video.color = _project_color(video, student)
    video.avg_rating = _round1(video.school_video_ratings.aggregate(a=Avg('value'))['a'])
    _attach_media_dims(video)
    comments = video.school_video_comments.order_by('-created_at')[:10]

    scoped_projects = projects.filter(
        id__in=projects.annotate(rc=Count('school_video_ratings')).filter(rc=0).values('id')
    )
    if student_filter:
        scoped_projects = scoped_projects.filter(user=student_filter.user)
        ids = list(scoped_projects.order_by('id').values_list('id', flat=True))
    else:
        ids = list(scoped_projects.order_by('-id').values_list('id', flat=True))
    next_video = None
    current_index = 0
    if ids:
        try:
            idx = ids.index(video.pk)
        except ValueError:
            idx = -1
        if student_filter and idx > 0:
            ids = ids[idx:] + ids[:idx]
            idx = 0
        current_index = idx + 1
        if len(ids) > 1:
            next_pk = ids[(idx + 1) % len(ids)]
            if next_pk != video.pk:
                nv = scoped_projects.get(pk=next_pk)
                nv.student = by_user.get(nv.user_id)
                nv.color = _project_color(nv, nv.student)
                next_video = nv

    user_rating = None
    all_rated = False
    if request.user.is_authenticated:
        ur = video.school_video_ratings.filter(user=request.user).first()
        if ur:
            user_rating = ur.value
        if student_filter and ids:
            rated_ids = set(
                SchoolVideoRating.objects.filter(
                    project_id__in=ids, user=request.user
                ).values_list('project_id', flat=True)
            )
            all_rated = set(ids) == rated_ids

    return render(request, 'school/video_rating.html', {
        'school': school,
        'video': video,
        'comments': comments,
        'next_video': next_video,
        'videos_total': len(ids),
        'current_index': current_index,
        'student_filter': student_filter,
        'user_rating': user_rating,
        'all_rated': all_rated,
    })


def _clamp_stars(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, min(5, value))


@require_POST
def rate_school_video(request, school_slug, pk):
    school = _get_school(request, school_slug)
    projects, _ = _school_projects(school)
    video = get_object_or_404(projects, pk=pk)
    value = _clamp_stars(request.POST.get('value'))
    if value is None:
        return JsonResponse({'ok': False, 'error': 'value required'}, status=400)
    user = request.user if request.user.is_authenticated else None
    if user:
        obj, _ = SchoolVideoRating.objects.update_or_create(
            project=video, user=user, defaults={'value': value},
        )
    else:
        obj = SchoolVideoRating.objects.create(project=video, value=value)
    avg = _round1(video.school_video_ratings.aggregate(a=Avg('value'))['a'])
    count = video.school_video_ratings.count()
    return JsonResponse({'ok': True, 'average': float(avg) if avg is not None else None, 'count': count})


@require_POST
def rate_school_student(request, school_slug, username):
    student = get_object_or_404(SchoolStudent, school__slug=school_slug, user__username=username)
    value = _clamp_stars(request.POST.get('value'))
    if value is None:
        return JsonResponse({'ok': False, 'error': 'value required'}, status=400)
    SchoolStudentRating.objects.create(student=student, value=value)
    avg = _round1(student.average_rating())
    count = student.ratings.count()
    return JsonResponse({'ok': True, 'average': float(avg) if avg is not None else None, 'count': count})


@require_POST
def comment_school_video(request, school_slug, pk):
    school = _get_school(request, school_slug)
    projects, _ = _school_projects(school)
    video = get_object_or_404(projects, pk=pk)
    body = (request.POST.get('body') or '').strip()
    if not body:
        return JsonResponse({'ok': False, 'error': 'body required'}, status=400)
    if request.user.is_authenticated:
        author_name = request.user.username
    else:
        author_name = (request.POST.get('author') or 'Guest').strip()[:80] or 'Guest'
    stars = _clamp_stars(request.POST.get('stars')) or 5
    comment = SchoolVideoComment.objects.create(
        project=video,
        author_name=author_name,
        body=body,
        stars=stars,
    )
    return JsonResponse({
        'ok': True,
        'id': comment.id,
        'author_name': comment.author_name,
        'stars': comment.stars,
        'body': comment.body,
        'time_label': comment.time_label(),
    })
