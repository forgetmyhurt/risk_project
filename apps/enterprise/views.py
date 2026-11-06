from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from apps.accounts.decorators import login_required_custom
from apps.enterprise.models import Enterprise

@login_required_custom
def index(request):
    total = Enterprise.objects.count()
    low_cnt = Enterprise.objects.filter(risk_level="L").count()
    mid_cnt = Enterprise.objects.filter(risk_level="M").count()
    high_cnt = Enterprise.objects.filter(risk_level="H").count()
    top_risks = Enterprise.objects.order_by("score_total", "id")[:10]
    return render(request, "index.html", {
        "total": total, "low_cnt": low_cnt, "mid_cnt": mid_cnt,
        "high_cnt": high_cnt, "top_risks": top_risks,
    })

@login_required_custom
def enterprise_list(request):
    """FR-01-01: 企业信息列表组合筛选与分页"""
    qs = Enterprise.objects.all().order_by("id")
    keyword = request.GET.get("keyword", "").strip()
    category = request.GET.get("category", "").strip()
    status = request.GET.get("status", "").strip()
    level = request.GET.get("level", "").strip()

    if keyword:
        qs = qs.filter(Q(firm_name__icontains=keyword) | Q(usc_code__icontains=keyword))
    if category in ("E", "P"):
        qs = qs.filter(firm_category=category)
    if status in ("1", "2", "3"):
        qs = qs.filter(ope_status=status)
    if level in ("L", "M", "H"):
        qs = qs.filter(risk_level=level)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "enterprise_list.html", {
        "page_obj": page_obj,
        "keyword": keyword,
        "category": category,
        "status": status,
        "level": level,
    })

@login_required_custom
def enterprise_detail(request, pk: int):
    """FR-01-02: 企业详情查看（工商/经营/地域/风险概览四块）"""
    ent = get_object_or_404(Enterprise, pk=pk)
    latest_ind = ent.indicators.order_by("-scored_at", "-id").first()
    return render(request, "enterprise_detail.html", {
        "ent": ent,
        "ind": latest_ind,
    })
