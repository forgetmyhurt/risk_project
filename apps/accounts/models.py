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