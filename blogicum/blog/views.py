from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CommentForm, PostForm, UserEditForm
from .models import Category, Comment, Post

User = get_user_model()

POSTS_PER_PAGE = 10


def paginate_page(request, queryset):
    paginator = Paginator(queryset, POSTS_PER_PAGE)
    page_number = request.GET.get('page')
    return paginator.get_page(page_number)


def annotate_comment_count(queryset):
    return queryset.annotate(_comment_count=Count('comments'))


def get_published_posts():
    return annotate_comment_count(
        Post.objects.filter(
            pub_date__lte=timezone.now(),
            is_published=True,
            category__is_published=True,
        ).select_related(
            'category', 'location', 'author'
        ).order_by('-pub_date')
    )


def get_profile_posts(profile_user, viewer):
    post_list = annotate_comment_count(
        Post.objects.filter(author=profile_user).select_related(
            'category', 'location', 'author'
        )
    )
    if not (viewer.is_authenticated and viewer == profile_user):
        post_list = post_list.filter(
            is_published=True,
            pub_date__lte=timezone.now(),
            category__is_published=True,
        )
    return post_list.order_by('-pub_date')


def get_post_for_detail(user, post_id):
    post = get_object_or_404(
        Post.objects.select_related('category', 'location', 'author'),
        pk=post_id,
    )
    if user.is_authenticated and user == post.author:
        return post
    if (
        post.is_published
        and post.category is not None
        and post.category.is_published
        and post.pub_date <= timezone.now()
    ):
        return post
    return None


def profile(request, username):
    profile_user = get_object_or_404(User, username=username)
    post_list = get_profile_posts(profile_user, request.user)
    context = {
        'profile': profile_user,
        'page_obj': paginate_page(request, post_list),
    }
    return render(request, 'blog/profile.html', context)


@login_required
def create_post(request):
    template_name = 'blog/create.html'
    if request.method == 'POST':
        form = PostForm(
            request.POST,
            files=request.FILES,
            user=request.user,
        )
        if form.is_valid():
            form.save()
            return redirect(
                'blog:profile',
                username=request.user.username,
            )
    else:
        form = PostForm(user=request.user)
    return render(request, template_name, {'form': form})


def _user_can_manage_post(user, post):
    return user == post.author or user.is_staff or user.is_superuser


@login_required
def edit_post(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if request.user != post.author:
        return redirect('blog:post_detail', post_id=post_id)
    template_name = 'blog/create.html'
    if request.method == 'POST':
        form = PostForm(
            request.POST,
            files=request.FILES,
            instance=post,
            user=request.user,
        )
        if form.is_valid():
            form.save()
            return redirect('blog:post_detail', post_id=post_id)
    else:
        form = PostForm(instance=post, user=request.user)
    return render(request, template_name, {'form': form})


@login_required
def delete_post(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if not _user_can_manage_post(request.user, post):
        return redirect('blog:post_detail', post_id=post_id)
    template_name = 'blog/create.html'
    if request.method == 'POST':
        post.delete()
        return redirect('blog:index')
    return render(
        request,
        template_name,
        {'form': PostForm(instance=post, user=request.user)},
    )


@login_required
def edit_profile(request):
    template_name = 'blog/user.html'
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('blog:profile', username=request.user.username)
    else:
        form = UserEditForm(instance=request.user)
    return render(request, template_name, {'form': form})


def index(request):
    context = {
        'page_obj': paginate_page(request, get_published_posts()),
    }
    return render(request, 'blog/index.html', context)


def post_detail(request, post_id):
    post = get_post_for_detail(request.user, post_id)
    if post is None:
        raise Http404
    context = {
        'post': post,
        'form': CommentForm(),
        'comments': post.comments.select_related('author'),
    }
    return render(request, 'blog/detail.html', context)


def _user_can_manage_comment(user, comment):
    return user == comment.author or user.is_staff or user.is_superuser


@login_required
def add_comment(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.author = request.user
        comment.post = post
        comment.save()
    return redirect('blog:post_detail', post_id=post_id)


@login_required
def edit_comment(request, post_id, comment_id):
    comment = get_object_or_404(
        Comment.objects.filter(post_id=post_id),
        pk=comment_id,
    )
    if not _user_can_manage_comment(request.user, comment):
        return redirect('blog:post_detail', post_id=post_id)
    template_name = 'blog/comment.html'
    if request.method == 'POST':
        form = CommentForm(request.POST, instance=comment)
        if form.is_valid():
            form.save()
            return redirect('blog:post_detail', post_id=post_id)
    else:
        form = CommentForm(instance=comment)
    return render(
        request,
        template_name,
        {'form': form, 'comment': comment},
    )


@login_required
def delete_comment(request, post_id, comment_id):
    comment = get_object_or_404(
        Comment.objects.filter(post_id=post_id),
        pk=comment_id,
    )
    if not _user_can_manage_comment(request.user, comment):
        return redirect('blog:post_detail', post_id=post_id)
    if request.method == 'POST':
        comment.delete()
        return redirect('blog:post_detail', post_id=post_id)
    return render(request, 'blog/comment.html', {'comment': comment})


def category_posts(request, category_slug):
    category = get_object_or_404(
        Category.objects.filter(is_published=True), slug=category_slug)
    post_list = annotate_comment_count(
        Post.objects.filter(
            category=category,
            is_published=True,
            pub_date__lte=timezone.now(),
        ).select_related(
            'category', 'location', 'author'
        ).order_by('-pub_date')
    )
    context = {
        'category': category,
        'page_obj': paginate_page(request, post_list),
    }
    return render(request, 'blog/category.html', context)
