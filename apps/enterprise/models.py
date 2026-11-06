from django.db import models

class Enterprise(models.Model):
    class FirmCategory(models.TextChoices):
        ENTERPRISE = "E", "企业"
        INDIVIDUAL = "P", "个体户"

    class OpeStatus(models.TextChoices):
        OPEN = "1", "在营"
        CANCELLED = "2", "注销"
        REVOKED = "3", "吊销"

    class RiskLevel(models.TextChoices):
        LOW = "L", "低风险"
        MID = "M", "中风险"
        HIGH = "H", "高风险"

    firm_eid = models.CharField("企业唯一标识", max_length=64, unique=True, null=True, blank=True)
    firm_name = models.CharField("企业名称", max_length=200, db_index=True)
    usc_code = models.CharField("统一社会信用代码", max_length=18, unique=True, null=True, blank=True)
    legal_rep = models.CharField("法定代表人", max_length=50, blank=True, default="", db_index=True)
    firm_category = models.CharField("企业类别", max_length=1, choices=FirmCategory.choices, default="E")
    firm_type = models.CharField("企业类型", max_length=100, blank=True, default="")
    ope_status = models.CharField("经营状态", max_length=2, choices=OpeStatus.choices, default="1", db_index=True)
    est_date = models.DateField("成立日期", null=True, blank=True, db_index=True)
    reg_cap = models.DecimalField("注册资本（万元）", max_digits=14, decimal_places=2, default=0)
    ind_econ_name = models.CharField("行业名称", max_length=100, blank=True, default="", db_index=True)
    province = models.CharField("省份", max_length=50, blank=True, default="", db_index=True)
    city = models.CharField("城市", max_length=50, blank=True, default="", db_index=True)
    district = models.CharField("区县", max_length=50, blank=True, default="")
    reg_agency = models.CharField("登记机关", max_length=100, blank=True, default="")
    business_scope = models.TextField("经营范围", blank=True, default="")
    risk_level = models.CharField("最新风险等级", max_length=1, choices=RiskLevel.choices, blank=True, default="L")
    score_total = models.DecimalField("最新综合得分", max_digits=5, decimal_places=2, default=100, db_index=True)
    last_scored_at = models.DateTimeField("最近一次评分时间", null=True, blank=True)
    extra = models.JSONField("其余工商字段", null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "enterprise"
        verbose_name = "企业"
        indexes = [
            models.Index(fields=["firm_category", "ope_status"], name="idx_cat_status"),
            models.Index(fields=["score_total"], name="idx_score_total"),
        ]

    def __str__(self):
        return self.firm_name
    