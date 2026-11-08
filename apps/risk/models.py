from django.db import models

class RiskIndicator(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = "L", "低风险"
        MID = "M", "中风险"
        HIGH = "H", "高风险"

    enterprise = models.ForeignKey(
        "enterprise.Enterprise", on_delete=models.CASCADE,
        related_name="indicators", verbose_name="所属企业"
    )
    batch_no = models.CharField("评分批次", max_length=32, default="20261103-01")
    cai_1 = models.PositiveSmallIntegerField("近1年被裁判次数", default=0)
    cai_2 = models.PositiveSmallIntegerField("近2年被裁判次数", default=0)
    cai_3 = models.PositiveSmallIntegerField("近3年被裁判次数", default=0)
    s_an_1 = models.PositiveSmallIntegerField("近1年立案数", default=0)
    s_an_2 = models.PositiveSmallIntegerField("近2年立案数", default=0)
    s_an_3 = models.PositiveSmallIntegerField("近3年立案数", default=0)
    li_an_1 = models.PositiveSmallIntegerField("近1年被立案次数", default=0)
    li_an_2 = models.PositiveSmallIntegerField("近2年被立案次数", default=0)
    li_an_3 = models.PositiveSmallIntegerField("近3年被立案次数", default=0)
    zhi_1 = models.PositiveSmallIntegerField("近1年被执行次数", default=0)
    zhi_2 = models.PositiveSmallIntegerField("近2年被执行次数", default=0)
    zhi_3 = models.PositiveSmallIntegerField("近3年被执行次数", default=0)
    score_fin = models.DecimalField("财务维度得分", max_digits=5, decimal_places=2, default=25)
    score_ope = models.DecimalField("经营维度得分", max_digits=5, decimal_places=2, default=25)
    score_com = models.DecimalField("合规维度得分", max_digits=5, decimal_places=2, default=25)
    score_qua = models.DecimalField("质量维度得分", max_digits=5, decimal_places=2, default=25)
    total_risk_score = models.DecimalField("综合得分", max_digits=5, decimal_places=2, default=100, db_index=True)
    risk_level = models.CharField("风险等级", max_length=1, choices=RiskLevel.choices, default="L")
    algo_version = models.CharField("公式版本", max_length=20, default="v1.0")
    name = models.CharField("企业名称（冗余）", max_length=200, blank=True, default="", db_index=True)
    usc_code = models.CharField("信用代码（冗余）", max_length=18, blank=True, default="")
    ope_status = models.CharField("经营状态（冗余）", max_length=2, blank=True, default="")
    scored_at = models.DateTimeField("评分时间", db_index=True)
    is_current = models.BooleanField("是否最新批次", default=True, db_index=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "risk_indicator"
        constraints = [
            models.UniqueConstraint(fields=["enterprise", "batch_no"], name="uk_ent_batch")
        ]
        indexes = [
            models.Index(fields=["enterprise", "scored_at"], name="idx_ent_scored"),
            models.Index(fields=["risk_level", "total_risk_score"], name="idx_level_score"),
        ]
