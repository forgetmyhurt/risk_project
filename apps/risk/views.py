from datetime import datetime
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from apps.accounts.decorators import login_required_custom
from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator
from services.report_build import build_report_context, generate_report_pdf
from services.risk_calc import calc_risk_score
from apps.accounts.models import UserActivityLog, log_activity

@login_required_custom
def risk_list(request):
    """FR-01-03: 风险指标列表（支持筛选、排序、分页，默认按综合得分倒序）"""
    qs = RiskIndicator.objects.select_related("enterprise").filter(is_current=True)
    keyword = request.GET.get("keyword", "").strip()
    level = request.GET.get("level", "").strip()
    order = request.GET.get("order", "-total_risk_score").strip()

    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(usc_code__icontains=keyword))
    if level in ("L", "M", "H"):
        qs = qs.filter(risk_level=level)
    if order not in ("total_risk_score", "-total_risk_score"):
        order = "-total_risk_score"
    qs = qs.order_by(order, "id")

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    return render(request, "risk_list.html", {
        "page_obj": page_obj,
        "keyword": keyword,
        "level": level,
        "order": order,
    })

@login_required_custom
def risk_detail(request, pk: int):
    """风险详情页：展示 12 项原始指标與四维度得分"""
    ind = get_object_or_404(RiskIndicator.objects.select_related("enterprise"), pk=pk)
    return render(request, "risk_detail.html", {"ind": ind, "ent": ind.enterprise})

@require_http_methods(["POST"])
@login_required_custom
def score_calc(request, pk: int):
    """FR-03-01: 发起评分计算（按企业+批次幂等更新，同步刷新企业表）"""
    ent = get_object_or_404(Enterprise, pk=pk)
    latest = ent.indicators.order_by("-scored_at", "-id").first()
    raw_metrics = {
        f: getattr(latest, f, 0)
        for f in ("cai_1", "cai_2", "cai_3", "s_an_1", "s_an_2", "s_an_3",
                  "li_an_1", "li_an_2", "li_an_3", "zhi_1", "zhi_2", "zhi_3")
    } if latest else {}

    res = calc_risk_score(raw_metrics)
    now = datetime.now()
    batch_no = latest.batch_no if latest else now.strftime("%Y%m%d-01")

    with transaction.atomic():
        ind, _ = RiskIndicator.objects.update_or_create(
            enterprise=ent,
            batch_no=batch_no,
            defaults={
                **res,
                "name": ent.firm_name,
                "usc_code": ent.usc_code or "",
                "ope_status": ent.ope_status,
                "scored_at": now,
                "is_current": True,
            },
        )
        ent.risk_level = res["risk_level"]
        ent.score_total = res["total_risk_score"]
        ent.last_scored_at = now
        ent.save(update_fields=["risk_level", "score_total", "last_scored_at", "update_time"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "code": 0,
            "data": {
                "record_id": ind.id,
                "score_fin": float(ind.score_fin),
                "score_ope": float(ind.score_ope),
                "score_com": float(ind.score_com),
                "score_qua": float(ind.score_qua),
                "total_score": float(ind.total_risk_score),
                "risk_level": ind.risk_level,
                "algo_version": ind.algo_version,
            }
        })
    log_activity(request, UserActivityLog.ActionType.SCORE,
                 f"发起风险重算：{ent.firm_name}（得分 {ind.total_risk_score}）")
    return redirect("risk:report", pk=ind.id)

@login_required_custom
def risk_report(request, pk: int):
    """FR-03-03: 风险报告四章节页面"""
    ind = get_object_or_404(RiskIndicator.objects.select_related("enterprise"), pk=pk)
    ctx = build_report_context(ind)
    return render(request, "report.html", ctx)

@login_required_custom
def report_pdf(request, pk: int):
    """FR-03-04: 导出 PDF 风险报告"""
    ind = get_object_or_404(RiskIndicator.objects.select_related("enterprise"), pk=pk)

    try:
        pdf_bytes, encoded_name = generate_report_pdf(ind)
    except Exception as e:
        return JsonResponse({"code": 500, "message": f"报告生成失败：{e}"}, status=500)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_name}"
    log_activity(request, UserActivityLog.ActionType.EXPORT, f"导出 PDF 风险报告：{ind.enterprise.firm_name}")

    return response

# 在 apps/risk/views.py 末尾追加以下代码
@require_http_methods(["POST"])
@login_required_custom
def sandbox_calc_api(request, pk: int):
    """迭代点5：风险评分沙箱模拟器（What-If Analysis），纯内存计算不写库"""
    ent = get_object_or_404(Enterprise, pk=pk)
    latest = ent.indicators.order_by("-scored_at", "-id").first()

    metric_keys = (
        "cai_1", "cai_2", "cai_3",
        "s_an_1", "s_an_2", "s_an_3",
        "li_an_1", "li_an_2", "li_an_3",
        "zhi_1", "zhi_2", "zhi_3",
    )
    sim_input = {k: request.POST.get(k, 0) for k in metric_keys}

    # 读取后台配置的动态阈值（默认 80 / 50）
    from apps.manager.views import SYS_CONFIG
    low_th = float(SYS_CONFIG.get("threshold_low", 80.0))
    mid_th = float(SYS_CONFIG.get("threshold_mid", 50.0))

    sim_res = calc_risk_score(sim_input, low_th=low_th, mid_th=mid_th)

    base_total = float(latest.total_risk_score) if latest else float(ent.score_total)
    base_level = latest.risk_level if latest else ent.risk_level
    sim_total = float(sim_res["total_risk_score"])
    diff = round(sim_total - base_total, 2)

    level_cn = {"L": "低风险", "M": "中风险", "H": "高风险"}
    return JsonResponse({
        "code": 0,
        "data": {
            "base_total": base_total,
            "base_level": base_level,
            "base_level_cn": level_cn.get(base_level, "低风险"),
            "sim_total": sim_total,
            "sim_level": sim_res["risk_level"],
            "sim_level_cn": level_cn.get(sim_res["risk_level"], "低风险"),
            "diff": diff,
            "scores": [
                float(sim_res["score_fin"]),
                float(sim_res["score_ope"]),
                float(sim_res["score_com"]),
                float(sim_res["score_qua"]),
            ],
        },
    })
