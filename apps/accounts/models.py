from django.conf import settings
from django.db import models

class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "管理员"
        NORMAL = "normal", "普通用户"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="profile", verbose_name="关联用户"
    )
    role = models.CharField("角色", max_length=20, choices=Role.choices, default=Role.NORMAL)
    department = models.CharField("所属部门", max_length=100, blank=True, default="")
    phone = models.CharField("联系电话", max_length=20, blank=True, default="")

    class Meta:
        db_table = "user_profile"
        verbose_name = "用户扩展"

    def __str__(self):
        return f"{self.user.username}（{self.get_role_display()}）"


class UserActivityLog(models.Model):
    class ActionType(models.TextChoices):
        AUTH = "auth", "认证安全"
        QUERY = "query", "数据检索"
        SCORE = "score", "风险评估"
        EXPORT = "export", "报告导出"
        MANAGE = "manage", "系统管理"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="activity_logs", verbose_name="操作用户"
    )
    username = models.CharField("用户名快照", max_length=150, default="")
    action_type = models.CharField("行为类别", max_length=20, choices=ActionType.choices, default=ActionType.QUERY)
    action_desc = models.CharField("操作详情", max_length=255)
    ip_address = models.CharField("IP地址", max_length=64, blank=True, default="")
    create_time = models.DateTimeField("操作时间", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "user_activity_log"
        ordering = ["-create_time", "-id"]
        verbose_name = "用户活动日志"


def log_activity(request, action_type: str, action_desc: str, user=None):
    """统一写入用户活动日志"""
    u = user or (request.user if getattr(request, "user", None) and request.user.is_authenticated else None)
    uname = u.username if u else "anonymous"
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    UserActivityLog.objects.create(
        user=u,
        username=uname,
        action_type=action_type,
        action_desc=action_desc[:255],
        ip_address=ip[:64],
    )
