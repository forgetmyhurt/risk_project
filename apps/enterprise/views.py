from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from apps.accounts.decorators import login_required_custom
from apps.accounts.models import UserActivityLog, log_activity
from apps.enterprise.models import Enterprise
# 在 apps/enterprise/views.py 顶部补充导入 json 和 build_enterprise_risk_graph：
import json
from services.archive_cleaner import extract_clean_archive_rows, format_region_display
from services.risk_graph import build_enterprise_risk_graph
# 在 apps/enterprise/views.py 顶部导入中增加 enrich_enterprises_for_table：
from services.archive_cleaner import (
    build_full_enterprise_archive,
    enrich_enterprises_for_table,
    extract_clean_archive_rows,
    format_region_display,
)

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


from services.archive_cleaner import enrich_enterprises_for_table


@login_required_custom
def index(request):
    total = Enterprise.objects.count()
    low_cnt = Enterprise.objects.filter(risk_level="L").count()
    mid_cnt = Enterprise.objects.filter(risk_level="M").count()
    high_cnt = Enterprise.objects.filter(risk_level="H").count()
    # 使用 enrich_enterprises_for_table 挂载 18 列所需的全部扩展与风控属性
    top_risks = enrich_enterprises_for_table(
        Enterprise.objects.order_by("score_total", "id")[:10]
    )
    recent_logs = UserActivityLog.objects.all()[:12]
    return render(request, "index.html", {
        "total": total, "low_cnt": low_cnt, "mid_cnt": mid_cnt,
        "high_cnt": high_cnt, "top_risks": top_risks, "recent_logs": recent_logs,
    })

@login_required_custom
def enterprise_list(request):
    """支持常规筛选与全部可视化图表点击下钻（得分段/企业类型/登记机关/行业/资本区间/年份/状态/等级）"""
    qs = Enterprise.objects.all().order_by("id")

    keyword = request.GET.get("keyword", "").strip()
    category = request.GET.get("category", "").strip()
    status = request.GET.get("status", "").strip()
    level = request.GET.get("level", "").strip()

    # 图表下钻专属过滤参数
    score_bin = request.GET.get("score_bin", "").strip()      # 如 "70~80"
    firm_type = request.GET.get("firm_type", "").strip()      # 如 "有限责任公司(自然人独资)"
    agency = request.GET.get("agency", "").strip()            # 如 "重庆市渝北区市场监督管理局"
    industry = request.GET.get("industry", "").strip()        # 如 "批发业"
    cap_range = request.GET.get("cap_range", "").strip()      # 如 "100-500万"
    est_year = request.GET.get("est_year", "").strip()        # 如 "2018"

    drill_tags = []

    if keyword:
        qs = qs.filter(
            Q(firm_name__icontains=keyword)
            | Q(usc_code__icontains=keyword)
            | Q(legal_rep__icontains=keyword)
        )
    if category in ("E", "P"):
        qs = qs.filter(firm_category=category)
        cat_map = {"E": "企业", "P": "个体户"}
        drill_tags.append(f"主体类别：{cat_map[category]}")
    if status in ("1", "2", "3"):
        qs = qs.filter(ope_status=status)
        status_map = {"1": "在营", "2": "注销", "3": "吊销"}
        drill_tags.append(f"经营状态：{status_map[status]}")
    if level in ("L", "M", "H"):
        qs = qs.filter(risk_level=level)
        lvl_map = {"L": "低风险", "M": "中风险", "H": "高风险"}
        drill_tags.append(f"风险等级：{lvl_map[level]}")

    # 1. 综合得分胶囊直方图下钻 (如 score_bin="50~60")
    if score_bin and "~" in score_bin:
        try:
            lo_str, hi_str = score_bin.split("~", 1)
            lo, hi = float(lo_str), float(hi_str)
            if hi >= 100:
                qs = qs.filter(score_total__gte=lo, score_total__lte=100)
            else:
                qs = qs.filter(score_total__gte=lo, score_total__lt=hi)
            qs = qs.order_by("-score_total", "id")
            drill_tags.append(f"综合得分区间：{score_bin} 分")
        except ValueError:
            pass

    # 2. 各企业类型四维对比图 / 气泡图下钻
    if firm_type:
        qs = qs.filter(firm_type__icontains=firm_type)
        drill_tags.append(f"企业类型：{firm_type}")

    # 3. 登记机关管辖集中度条形图下钻
    if agency:
        qs = qs.filter(reg_agency__icontains=agency)
        drill_tags.append(f"主管登记机关：{agency}")

    # 4. 行业分布气泡/柱状图下钻
    if industry:
        qs = qs.filter(ind_econ_name__icontains=industry)
        drill_tags.append(f"所属行业：{industry}")

    # 5. 注册资本分布图下钻
    if cap_range:
        if "100万以下" in cap_range or "<100" in cap_range or "0~100" in cap_range:
            qs = qs.filter(reg_cap__lt=100)
        elif "100-500" in cap_range or "100~500" in cap_range:
            qs = qs.filter(reg_cap__gte=100, reg_cap__lt=500)
        elif "500-1000" in cap_range or "500~1000" in cap_range:
            qs = qs.filter(reg_cap__gte=500, reg_cap__lt=1000)
        elif "1000-5000" in cap_range or "1000~5000" in cap_range:
            qs = qs.filter(reg_cap__gte=1000, reg_cap__lt=5000)
        elif "5000" in cap_range:
            qs = qs.filter(reg_cap__gte=5000)
        drill_tags.append(f"注册资本：{cap_range}")

    # 6. 成立年份趋势图下钻
    if est_year and est_year[:4].isdigit():
        qs = qs.filter(est_date__year=int(est_year[:4]))
        drill_tags.append(f"成立年份：{est_year[:4]} 年")

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    page_obj.object_list = enrich_enterprises_for_table(page_obj.object_list)

    # 保留除 page 外的全部 GET 参数供分页按钮拼接
    query_params = request.GET.copy()
    query_params.pop("page", None)
    extra_query = query_params.urlencode()

    return render(request, "enterprise_list.html", {
        "page_obj": page_obj,
        "keyword": keyword,
        "category": category,
        "status": status,
        "level": level,
        "score_bin": score_bin,
        "firm_type": firm_type,
        "agency": agency,
        "industry": industry,
        "cap_range": cap_range,
        "est_year": est_year,
        "drill_tags": drill_tags,
        "extra_query": extra_query,
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

# 1. 在 apps/enterprise/views.py 顶部的导入语句中更新为：
from services.archive_cleaner import (
    build_full_enterprise_archive,
    extract_clean_archive_rows,
    format_region_display,
)

# 2. 将 enterprise_detail 视图函数更新为：
@login_required_custom
def enterprise_detail(request, pk: int):
    ent = get_object_or_404(Enterprise, pk=pk)
    latest_ind = ent.indicators.order_by("-scored_at", "-id").first()
    graph_data = build_enterprise_risk_graph(ent)
    archive_bundle = build_full_enterprise_archive(ent)

    base_scores = [
        float(latest_ind.score_fin) if latest_ind else 25.0,
        float(latest_ind.score_ope) if latest_ind else 25.0,
        float(latest_ind.score_com) if latest_ind else 25.0,
        float(latest_ind.score_qua) if latest_ind else 25.0,
    ]
    log_activity(request, UserActivityLog.ActionType.QUERY, f"查看企业全量详情：{ent.firm_name}")
    return render(request, "enterprise_detail.html", {
        "ent": ent,
        "ind": latest_ind,
        "region_display": format_region_display(ent.province, ent.city, ent.district),
        "core_extra": archive_bundle["core_extra"],
        "remaining_rows": archive_bundle["remaining_rows"],
        "total_field_count": archive_bundle["total_field_count"],
        "extra_rows": extract_clean_archive_rows(ent),
        "base_scores_json": json.dumps(base_scores),
        "graph_json": json.dumps(graph_data, ensure_ascii=False),
        "contagion_alerts": graph_data["contagion_alerts"],
        "high_risk_rel_count": graph_data["high_risk_count"],
    })
