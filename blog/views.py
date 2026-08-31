from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.contrib import messages
from .models import Post, Category, Tag
from .forms import PostForm

# ==========================================
# PUBLIC VIEWS (Subdomain: blog.skillifly.cloud)
# ==========================================

def post_list(request):
    posts = Post.objects.filter(status='published').select_related('author').prefetch_related('categories', 'tags')
    paginator = Paginator(posts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'blog/post_list.html', {'page_obj': page_obj})

def post_detail(request, slug):
    post = get_object_or_404(Post, slug=slug, status='published')
    return render(request, 'blog/post_detail.html', {'post': post})

def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    posts = category.posts.filter(status='published').select_related('author')
    paginator = Paginator(posts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'blog/post_list.html', {'page_obj': page_obj, 'category': category})

def tag_detail(request, slug):
    tag = get_object_or_404(Tag, slug=slug)
    posts = tag.posts.filter(status='published').select_related('author')
    paginator = Paginator(posts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'blog/post_list.html', {'page_obj': page_obj, 'tag': tag})


# ==========================================
# DASHBOARD VIEWS (Main Site: /manage/blog/)
# ==========================================

@login_required
def dashboard(request):
    posts = Post.objects.filter(author=request.user)
    return render(request, 'blog/dashboard.html', {'posts': posts})

@login_required
def post_create(request):
    if request.method == 'POST':
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            if request.POST.get('action') == 'draft':
                post.status = 'draft'
            post.save()
            form.save_m2m() # Save tags and categories
            messages.success(request, 'Blog post created successfully!')
            return redirect('blog_dashboard')
    else:
        form = PostForm()
    return render(request, 'blog/post_form.html', {'form': form, 'title': 'Create New Post'})

@login_required
def post_update(request, pk):
    post = get_object_or_404(Post, pk=pk, author=request.user)
    if request.method == 'POST':
        form = PostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            post = form.save(commit=False)
            if request.POST.get('action') == 'draft':
                post.status = 'draft'
            post.save()
            form.save_m2m()
            messages.success(request, 'Blog post updated successfully!')
            return redirect('blog_dashboard')
    else:
        form = PostForm(instance=post)
    return render(request, 'blog/post_form.html', {'form': form, 'title': f'Edit Post: {post.title}'})

@login_required
def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk, author=request.user)
    if request.method == 'POST':
        post.delete()
        messages.success(request, 'Blog post deleted successfully!')
        return redirect('blog_dashboard')
    return render(request, 'blog/post_confirm_delete.html', {'post': post})

# ==========================================
# AJAX API VIEWS (Dashboard)
# ==========================================
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json

@login_required
@require_POST
def api_create_category(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)
        
        # Check if it already exists (case-insensitive)
        category, created = Category.objects.get_or_create(name__iexact=name, defaults={'name': name})
        return JsonResponse({'id': category.id, 'name': category.name, 'slug': category.slug})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
@require_POST
def api_create_tag(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)
        
        tag, created = Tag.objects.get_or_create(name__iexact=name, defaults={'name': name})
        return JsonResponse({'id': tag.id, 'name': tag.name, 'slug': tag.slug})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
