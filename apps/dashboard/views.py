import json
from django.db.models import Avg, Count, Q
from django.shortcuts import render
from apps.accounts.decorators import login_required_custom
from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator

STATUS_MAP = {"1": "在营", "2": "注销", "3": "吊销"}

@login_required_custom
def chart_enterprise(request):
    """FR-02-01 ~ FR-02-03 + 悬浮气泡块样式企业分布"""
    total = Enterprise.objects.count()
    open_cnt = Enterprise.objects.filter(ope_status="1").count()
    cancel_cnt = Enterprise.objects.filter(ope_status="2").count()
    revoke_cnt = Enterprise.objects.filter(ope_status="3").count()

    # 1. 经营状态构成
    status_data = [
        {"name": "在营企业", "value": open_cnt, "code": "1", "itemStyle": {"color": "#10b981"}},
        {"name": "注销企业", "value": cancel_cnt, "code": "2", "itemStyle": {"color": "#94a3b8"}},
        {"name": "吊销企业", "value": revoke_cnt, "code": "3", "itemStyle": {"color": "#ef4444"}},
    ]

    # 2. 企业类型 TOP10 气泡与柱状数据
    type_qs = (
        Enterprise.objects.exclude(firm_type="")
        .values("firm_type")
        .annotate(cnt=Count("id"), avg_score=Avg("score_total"))
        .order_by("-cnt")[:10]
    )
    type_names = [r["firm_type"] for r in type_qs]
    type_vals = [r["cnt"] for r in type_qs]
    # 构造三维气泡块数据：[平均分, 企业数, 风险关注度半径, 类型名称]
    type_bubbles = [
        [round(float(r["avg_score"] or 90), 2), r["cnt"], max(18, min(65, int(r["cnt"] ** 0.5))), r["firm_type"]]
        for r in type_qs
    ]

    # 3. 登记机关集中度 TOP10
    agency_qs = (
        Enterprise.objects.exclude(reg_agency="")
        .values("reg_agency")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:10]
    )
    agency_names = [r["reg_agency"] for r in reversed(list(agency_qs))]
    agency_vals = [r["cnt"] for r in reversed(list(agency_qs))]

    return render(request, "chart_enterprise.html", {
        "total": total, "open_cnt": open_cnt, "cancel_cnt": cancel_cnt, "revoke_cnt": revoke_cnt,
        "status_json": json.dumps(status_data, ensure_ascii=False),
        "type_names_json": json.dumps(type_names, ensure_ascii=False),
        "type_vals_json": json.dumps(type_vals),
        "type_bubbles_json": json.dumps(type_bubbles, ensure_ascii=False),
        "agency_names_json": json.dumps(agency_names, ensure_ascii=False),
        "agency_vals_json": json.dumps(agency_vals),
    })

@login_required_custom
def chart_risk(request):
    """FR-02-04 ~ FR-02-06: 悬浮气泡块样式风险数据可视化"""
    lvl_qs = Enterprise.objects.values("risk_level").annotate(cnt=Count("id"))
    lvl_map = {r["risk_level"]: r["cnt"] for r in lvl_qs}
    low_c, mid_c, high_c = lvl_map.get("L", 0), lvl_map.get("M", 0), lvl_map.get("H", 0)

    level_data = [
        {"name": "低风险", "value": low_c, "level": "L", "itemStyle": {"color": "#1E7B45"}},
        {"name": "中风险", "value": mid_c, "level": "M", "itemStyle": {"color": "#B7791F"}},
        {"name": "高风险", "value": high_c, "level": "H", "itemStyle": {"color": "#C0392B"}},
    ]

    # 综合得分 10 分一档分箱
    bins = [f"{i}~{i+10}" for i in range(0, 100, 10)]
    bin_counts = [0] * 10
    for s in Enterprise.objects.values_list("score_total", flat=True):
        idx = min(int(float(s) // 10), 9)
        bin_counts[max(0, idx)] += 1

    # 各企业类型的四维度平均分对比
    top_types = list(
        Enterprise.objects.exclude(firm_type="")
        .values_list("firm_type", flat=True)
        .annotate(c=Count("id"))
        .order_by("-c")[:6]
    )
    avg_qs = (
        RiskIndicator.objects.filter(is_current=True, enterprise__firm_type__in=top_types)
        .values("enterprise__firm_type")
        .annotate(
            fin=Avg("score_fin"), ope=Avg("score_ope"),
            com=Avg("score_com"), qua=Avg("score_qua")
        )
    )
    avg_map = {r["enterprise__firm_type"]: r for r in avg_qs}
    t_labels, fin_list, ope_list, com_list, qua_list = [], [], [], [], []
    for t in top_types:
        if t in avg_map:
            t_labels.append(t[:10])
            fin_list.append(round(float(avg_map[t]["fin"] or 0), 2))
            ope_list.append(round(float(avg_map[t]["ope"] or 0), 2))
            com_list.append(round(float(avg_map[t]["com"] or 0), 2))
            qua_list.append(round(float(avg_map[t]["qua"] or 0), 2))

    return render(request, "chart_risk.html", {
        "low_c": low_c, "mid_c": mid_c, "high_c": high_c,
        "level_json": json.dumps(level_data, ensure_ascii=False),
        "bins_json": json.dumps(bins, ensure_ascii=False),
        "bin_counts_json": json.dumps(bin_counts),
        "t_labels_json": json.dumps(t_labels, ensure_ascii=False),
        "fin_json": json.dumps(fin_list),
        "ope_json": json.dumps(ope_list),
        "com_json": json.dumps(com_list),
        "qua_json": json.dumps(qua_list),
    })

@login_required_custom
def chart_compare(request):
    """FR-02-07: 单企四维度雷达图与差值气泡卡片对比"""
    ent_id = request.GET.get("id")
    samples = Enterprise.objects.order_by("score_total", "id")[:30]
    ent = Enterprise.objects.filter(pk=ent_id).first() if ent_id else samples.first()
    ind = ent.indicators.filter(is_current=True).first() if ent else None

    ent_scores = [
        float(ind.score_fin), float(ind.score_ope),
        float(ind.score_com), float(ind.score_qua)
    ] if ind else [25.0, 25.0, 25.0, 25.0]

    avg_q = RiskIndicator.objects.filter(is_current=True)
    if ent and ent.firm_type:
        avg_q = avg_q.filter(enterprise__firm_type=ent.firm_type)
    agg = avg_q.aggregate(fin=Avg("score_fin"), ope=Avg("score_ope"), com=Avg("score_com"), qua=Avg("score_qua"))
    avg_scores = [
        round(float(agg["fin"] or 24.0), 2),
        round(float(agg["ope"] or 24.0), 2),
        round(float(agg["com"] or 24.0), 2),
        round(float(agg["qua"] or 24.0), 2),
    ]
    dim_Compare = [
        {"name": n, "ent": round(e, 2), "avg": a, "diff": round(e - a, 2)}
        for n, e, a in zip(["财务维度", "经营维度", "合规维度", "质量维度"], ent_scores, avg_scores)
    ]

    return render(request, "chart_compare.html", {
        "samples": samples,
        "ent": ent,
        "dim_compare": dim_Compare,
        "ent_scores_json": json.dumps(ent_scores),
        "avg_scores_json": json.dumps(avg_scores),
    })
