from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from apps.accounts.decorators import admin_required
from apps.accounts.models import UserProfile
from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator

SYS_CONFIG = {"threshold_low": 80.0, "threshold_mid": 50.0, "timeout": 5}

@admin_required
def dashboard(request):
    return render(request, "manage_dashboard.html", {
        "ent_count": Enterprise.objects.count(),
        "ind_count": RiskIndicator.objects.count(),
        "user_count": User.objects.count(),
        "config": SYS_CONFIG,
    })

@admin_required
@require_http_methods(["GET", "POST"])
def user_list(request):
    if request.method == "POST":
        uid = request.POST.get("user_id")
        action = request.POST.get("action")
        u = User.objects.filter(pk=uid).first()
        if u and not u.is_superuser:
            if action == "toggle_active":
                u.is_active = not u.is_active
                u.save(update_fields=["is_active"])
            elif action in ("admin", "normal") and request.user.is_superuser:
                UserProfile.objects.update_or_create(user=u, defaults={"role": action})
        return JsonResponse({"code": 0, "message": "状态已更新"})

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
            return JsonResponse({"code": 0, "message": "阈值配置已保存", "data": SYS_CONFIG})
        except ValueError:
            return JsonResponse({"code": -1, "message": "参数格式错误"}, status=400)

    return render(request, "manage_threshold.html", {"config": SYS_CONFIG})
