from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from apps.enterprise.models import Enterprise
from .decorators import is_admin_user, login_required_custom
from .models import UserActivityLog, UserProfile, log_activity

def _safe_next_url(next_url: str) -> str:
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
                request.session.set_expiry(7 * 24 * 3600 if remember else 0)
                UserProfile.objects.get_or_create(
                    user=user,
                    defaults={"role": "admin" if (user.is_superuser or user.is_staff) else "normal"}
                )
                log_activity(request, UserActivityLog.ActionType.AUTH, "用户登录系统成功", user=user)
                return redirect(_safe_next_url(next_url))
            error = "用户名或密码错误"
    return render(request, "login.html", {"error": error, "next": next_url})

@require_http_methods(["POST"])
@login_required_custom
def logout_view(request):
    log_activity(request, UserActivityLog.ActionType.AUTH, "用户主动退出登录")
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
            log_activity(request, UserActivityLog.ActionType.AUTH, "新用户注册并登录", user=user)
            return redirect("/")
    return render(request, "register.html", {"error": error})

@require_http_methods(["GET", "POST"])
@login_required_custom
def profile_view(request):
    """个人主页与分层级仪表盘：融合个人资料修改、密码重置、角色专属仪表盘与活动日志"""
    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={"role": "admin" if (request.user.is_superuser or request.user.is_staff) else "normal"}
    )
    msg, err = "", ""
    if request.method == "POST":
        form_type = request.POST.get("form_type", "info")
        if form_type == "info":
            profile.department = request.POST.get("department", "").strip()[:100]
            profile.phone = request.POST.get("phone", "").strip()[:20]
            request.user.email = request.POST.get("email", "").strip()[:100]
            profile.save()
            request.user.save(update_fields=["email"])
            log_activity(request, UserActivityLog.ActionType.AUTH, "更新了个人主页资料")
            msg = "个人资料已成功更新"
        elif form_type == "pwd":
            old_p = request.POST.get("old_password", "")
            new_p = request.POST.get("new_password", "")
            if not request.user.check_password(old_p):
                err = "原密码验证失败"
            elif len(new_p) < 6:
                err = "新密码长度不能少于 6 位"
            else:
                request.user.set_password(new_p)
                request.user.save()
                update_session_auth_hash(request, request.user)
                log_activity(request, UserActivityLog.ActionType.AUTH, "修改了账户登录密码")
                msg = "登录密码修改成功"

    is_admin = is_admin_user(request.user)
    my_logs = UserActivityLog.objects.filter(user=request.user)[:15]
    all_logs = UserActivityLog.objects.all()[:25] if is_admin else None
    all_users = User.objects.select_related("profile").order_by("id") if is_admin else None

    return render(request, "profile.html", {
        "profile": profile,
        "is_admin": is_admin,
        "my_logs": my_logs,
        "all_logs": all_logs,
        "all_users": all_users,
        "ent_total": Enterprise.objects.count(),
        "high_risk_cnt": Enterprise.objects.filter(risk_level="H").count(),
        "msg": msg,
        "err": err,
    })

@require_http_methods(["GET", "POST"])
@login_required_custom
def password_change(request):
    return redirect("accounts:profile")
