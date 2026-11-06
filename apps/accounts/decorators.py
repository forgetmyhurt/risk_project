import logging
from functools import wraps
from urllib.parse import urlencode
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

logger = logging.getLogger("apps.accounts")

def _is_ajax(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )

def is_admin_user(user):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")

def _login_redirect(request):
    if _is_ajax(request):
        return JsonResponse({"code": 401, "message": "请先登录后再操作"}, status=401)
    url = f"{reverse('accounts:login')}?{urlencode({'next': request.get_full_path()})}"
    return redirect(url)

def _deny(request, message="权限不足，需要管理员权限"):
    logger.warning("权限拒绝 user=%s path=%s ip=%s", request.user, request.get_full_path(), request.META.get("REMOTE_ADDR"))
    if _is_ajax(request):
        return JsonResponse({"code": 403, "message": message}, status=403)
    return render(request, "403.html", {"message": message}, status=403)

def login_required_custom(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login_redirect(request)
        return view_func(request, *args, **kwargs)
    return _wrapped

def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login_redirect(request)
        if not is_admin_user(request.user):
            return _deny(request)
        return view_func(request, *args, **kwargs)
    return _wrapped

def superuser_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login_redirect(request)
        if not request.user.is_superuser:
            return _deny(request, "权限不足，仅超级用户可操作")
        return view_func(request, *args, **kwargs)
    return _wrapped
