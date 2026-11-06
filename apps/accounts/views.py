from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from .decorators import login_required_custom
from .models import UserProfile

def _safe_next_url(next_url: str) -> str:
    """仅接受以 / 开头且不含 // 的站内路径，防止开放重定向"""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")

    error = ""
    next_url = request.GET.get("next", "/")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()[:150]
        password = request.POST.get("password", "")[:128]
        remember = request.POST.get("remember")
        next_url = request.POST.get("next", "/")

        if not username or not password:
            error = "请输入用户名和密码"
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None and user.is_active:
                login(request, user)
                request.session.cycle_key()
                # FR-06-02: 勾选记住我保持 7 天，未勾选随浏览器关闭失效
                request.session.set_expiry(7 * 24 * 3600 if remember else 0)
                return redirect(_safe_next_url(next_url))
            error = "用户名或密码错误"

    return render(request, "login.html", {"error": error, "next": next_url})

@require_http_methods(["POST"])
@login_required_custom
def logout_view(request):
    logout(request)
    return redirect("/login/")

@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("/")

    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()[:150]
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        phone = request.POST.get("phone", "").strip()[:20]

        if not username or not password:
            error = "用户名和密码不能为空"
        elif password != password2:
            error = "两次输入的密码不一致"
        elif User.objects.filter(username=username).exists():
            error = "该用户名已存在"
        else:
            user = User.objects.create_user(username=username, password=password)
            UserProfile.objects.create(user=user, role=UserProfile.Role.NORMAL, phone=phone)
            login(request, user)
            request.session.set_expiry(0)
            return redirect("/")

    return render(request, "register.html", {"error": error})

@require_http_methods(["GET", "POST"])
@login_required_custom
def password_change(request):
    if request.method == "GET":
        return render(request, "password_change.html")

    old_pwd = request.POST.get("old_password", "")
    new_pwd = request.POST.get("new_password", "")
    if not request.user.check_password(old_pwd):
        return JsonResponse({"code": -1, "message": "原密码不正确"}, status=400)
    if len(new_pwd) < 6:
        return JsonResponse({"code": -1, "message": "新密码长度不能少于 6 位"}, status=400)

    request.user.set_password(new_pwd)
    request.user.save()
    update_session_auth_hash(request, request.user)
    return JsonResponse({"code": 0, "message": "密码修改成功"})
