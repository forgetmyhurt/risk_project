from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from apps.accounts.decorators import login_required_custom
from apps.accounts.models import UserActivityLog, log_activity
from apps.enterprise.models import Enterprise

LEVEL_KEYWORDS = {
    "低": "L", "低风险": "L", "l": "L",
    "中": "M", "中风险": "M", "m": "M",
    "高": "H", "高风险": "H", "h": "H",
}

def _build_omnibox_query(keyword: str) -> Q:
    """构建多字段智能匹配条件：名称 / 信用代码 / 编号 / 法定代表人 / 风险等级"""
    kw = keyword.strip()
    q = (
        Q(firm_name__icontains=kw)
        | Q(usc_code__icontains=kw)
        | Q(firm_eid__icontains=kw)
        | Q(legal_rep__icontains=kw)
    )
    if kw.isdigit():
        q |= Q(id=int(kw))
    mapped_lvl = LEVEL_KEYWORDS.get(kw.lower())
    if mapped_lvl:
        q |= Q(risk_level=mapped_lvl)
    return q

@login_required_custom
def index(request):
    total = Enterprise.objects.count()
    low_cnt = Enterprise.objects.filter(risk_level="L").count()
    mid_cnt = Enterprise.objects.filter(risk_level="M").count()
    high_cnt = Enterprise.objects.filter(risk_level="H").count()
    top_risks = Enterprise.objects.order_by("score_total", "id")[:10]
    recent_logs = UserActivityLog.objects.all()[:12]
    return render(request, "index.html", {
        "total": total, "low_cnt": low_cnt, "mid_cnt": mid_cnt,
        "high_cnt": high_cnt, "top_risks": top_risks, "recent_logs": recent_logs,
    })

@login_required_custom
def enterprise_list(request):
    """FR-01-01: 支持全局大搜索栏多字段匹配与条件筛选"""
    qs = Enterprise.objects.all().order_by("id")
    keyword = request.GET.get("keyword", "").strip()
    category = request.GET.get("category", "").strip()
    status = request.GET.get("status", "").strip()
    level = request.GET.get("level", "").strip()

    if keyword:
        qs = qs.filter(_build_omnibox_query(keyword))
        log_activity(request, UserActivityLog.ActionType.QUERY, f"全局检索关键字：“{keyword}”")
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
def search_suggest(request):
    """全局大搜索栏 AJAX 实时联想接口（返回前 6 条匹配企业）"""
    kw = request.GET.get("q", "").strip()
    if not kw:
        return JsonResponse({"code": 0, "items": []})

    qs = Enterprise.objects.filter(_build_omnibox_query(kw)).order_by("score_total", "id")[:6]
    items = [
        {
            "id": e.id,
            "firm_name": e.firm_name,
            "usc_code": e.usc_code or e.firm_eid or f"ID:{e.id}",
            "legal_rep": e.legal_rep or "-",
            "score_total": float(e.score_total),
            "risk_level": e.risk_level,
        }
        for e in qs
    ]
    return JsonResponse({"code": 0, "items": items})

@login_required_custom
def enterprise_detail(request, pk: int):
    ent = get_object_or_404(Enterprise, pk=pk)
    latest_ind = ent.indicators.order_by("-scored_at", "-id").first()
    log_activity(request, UserActivityLog.ActionType.QUERY, f"查看企业详情：{ent.firm_name} (ID:{ent.id})")
    return render(request, "enterprise_detail.html", {"ent": ent, "ind": latest_ind})
