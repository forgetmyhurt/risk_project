from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from apps.accounts.decorators import admin_required
from apps.accounts.models import UserActivityLog, UserProfile, log_activity
from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator

SYS_CONFIG = {"threshold_low": 80.0, "threshold_mid": 50.0, "timeout": 5}

@admin_required
def dashboard(request):
    users = User.objects.select_related("profile").order_by("id")
    recent_logs = UserActivityLog.objects.all()[:30]
    return render(request, "manage_dashboard.html", {
        "ent_count": Enterprise.objects.count(),
        "ind_count": RiskIndicator.objects.count(),
        "user_count": users.count(),
        "users": users,
        "recent_logs": recent_logs,
        "config": SYS_CONFIG,
    })

@admin_required
@require_http_methods(["GET", "POST"])
def user_list(request):
    if request.method == "POST":
        action = request.POST.get("action", "")
        # 1. 创建新账号
        if action == "create":
            uname = request.POST.get("username", "").strip()[:150]
            pwd = request.POST.get("password", "").strip()
            role = request.POST.get("role", "normal")
            dept = request.POST.get("department", "").strip()[:100]
            phone = request.POST.get("phone", "").strip()[:20]
            if not uname or len(pwd) < 6:
                return JsonResponse({"code": -1, "message": "用户名不能为空且密码至少 6 位"}, status=400)
            if User.objects.filter(username=uname).exists():
                return JsonResponse({"code": -1, "message": "该用户名已存在"}, status=400)
            # 仅超级用户或管理员可创建账号；赋权 admin 需管理员以上
            assigned_role = role if role in ("admin", "normal") else "normal"
            u = User.objects.create_user(username=uname, password=pwd, is_staff=(assigned_role == "admin"))
            UserProfile.objects.create(user=u, role=assigned_role, department=dept, phone=phone)
            log_activity(request, UserActivityLog.ActionType.MANAGE, f"创建账号 {uname}（角色：{assigned_role}）")
            return JsonResponse({"code": 0, "message": f"账号 {uname} 创建成功"})

        # 针对已有账号的操作
        uid = request.POST.get("user_id")
        target = User.objects.filter(pk=uid).first()
        if not target:
            return JsonResponse({"code": -1, "message": "目标账号不存在"}, status=404)
        if target.is_superuser or target == request.user:
            return JsonResponse({"code": -1, "message": "不能对超级用户或当前登录自身执行此操作"}, status=403)

        # 2. 启用 / 禁用账号
        if action == "toggle_active":
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            state_str = "启用" if target.is_active else "禁用"
            log_activity(request, UserActivityLog.ActionType.MANAGE, f"{state_str}了用户账号 {target.username}")
            return JsonResponse({"code": 0, "message": f"已{state_str}账号 {target.username}"})

        # 3. 授予 / 变更角色权限
        if action == "set_role":
            new_role = request.POST.get("role", "normal")
            if new_role not in ("admin", "normal"):
                return JsonResponse({"code": -1, "message": "无效的角色类型"}, status=400)
            UserProfile.objects.update_or_create(user=target, defaults={"role": new_role})
            target.is_staff = (new_role == "admin")
            target.save(update_fields=["is_staff"])
            log_activity(request, UserActivityLog.ActionType.MANAGE, f"将用户 {target.username} 权限变更为 {new_role}")
            return JsonResponse({"code": 0, "message": f"已将 {target.username} 角色更新为 {new_role}"})

        # 4. 删除账号
        if action == "delete":
            uname = target.username
            target.delete()
            log_activity(request, UserActivityLog.ActionType.MANAGE, f"删除了用户账号 {uname}")
            return JsonResponse({"code": 0, "message": f"账号 {uname} 已删除"})

        return JsonResponse({"code": -1, "message": "未知操作类型"}, status=400)

    users = User.objects.select_related("profile").order_by("id")
    return render(request, "manage_users.html", {"users": users})

@admin_required
@require_http_methods(["GET", "POST"])
def threshold_config(request):
    if request.method == "POST":
        try:
            low = float(request.POST.get("threshold_low", 80))
            mid = float(request.POST.get("threshold_mid", 50))
            timeout = int(request.POST.get("timeout", 5))
            if not (0 < mid < low <= 100):
                return JsonResponse({"code": -1, "message": "阈值须满足 0 < 中风险阈值 < 低风险阈值 <= 100"}, status=400)
            SYS_CONFIG.update({"threshold_low": low, "threshold_mid": mid, "timeout": timeout})
            log_activity(request, UserActivityLog.ActionType.MANAGE, f"更新风险阈值：低风险≥{low}，中风险≥{mid}")
            return JsonResponse({"code": 0, "message": "阈值配置已保存", "data": SYS_CONFIG})
        except ValueError:
            return JsonResponse({"code": -1, "message": "参数格式错误"}, status=400)
    return render(request, "manage_threshold.html", {"config": SYS_CONFIG})
