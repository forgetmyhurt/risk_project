import json
from django.db.models import Avg, Count
from django.shortcuts import render
from apps.accounts.decorators import login_required_custom
from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator

STATUS_MAP = {"1": "在营", "2": "注销", "3": "吊销"}
LEVEL_MAP = {"L": "低风险", "M": "中风险", "H": "高风险"}

@login_required_custom
def chart_enterprise(request):
    """FR-02-01 ~ FR-02-03: 企业数据可视化（经营状态环形图、企业类型TOP10柱状图、登记机关条形图）"""
    # 1. 经营状态构成 (FR-02-01)
    status_qs = Enterprise.objects.values("ope_status").annotate(cnt=Count("id")).order_by("-cnt")
    status_data = [
        {"name": STATUS_MAP.get(r["ope_status"], "其他"), "value": r["cnt"], "code": r["ope_status"]}
        for r in status_qs
    ]

    # 2. 企业类型 TOP10 (FR-02-02)
    type_qs = (
        Enterprise.objects.exclude(firm_type="")
        .values("firm_type")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:10]
    )
    type_names = [r["firm_type"] for r in type_qs]
    type_vals = [r["cnt"] for r in type_qs]

    # 3. 登记机关集中度 TOP10 (FR-02-03)
    agency_qs = (
        Enterprise.objects.exclude(reg_agency="")
        .values("reg_agency")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:10]
    )
    agency_names = [r["reg_agency"] for r in reversed(list(agency_qs))]
    agency_vals = [r["cnt"] for r in reversed(list(agency_qs))]

    return render(request, "chart_enterprise.html", {
        "status_json": json.dumps(status_data, ensure_ascii=False),
        "type_names_json": json.dumps(type_names, ensure_ascii=False),
        "type_vals_json": json.dumps(type_vals),
        "agency_names_json": json.dumps(agency_names, ensure_ascii=False),
        "agency_vals_json": json.dumps(agency_vals),
    })

@login_required_custom
def chart_risk(request):
    """FR-02-04 ~ FR-02-06: 风险数据可视化（风险等级环形图、得分分布直方图、类型平均风险分组条形图）"""
    # 1. 风险等级构成 (FR-02-04)
    lvl_qs = Enterprise.objects.values("risk_level").annotate(cnt=Count("id"))
    lvl_map = {r["risk_level"]: r["cnt"] for r in lvl_qs}
    level_data = [
        {"name": "低风险", "value": lvl_map.get("L", 0), "level": "L", "itemStyle": {"color": "#1E7B45"}},
        {"name": "中风险", "value": lvl_map.get("M", 0), "level": "M", "itemStyle": {"color": "#B7791F"}},
        {"name": "高风险", "value": lvl_map.get("H", 0), "level": "H", "itemStyle": {"color": "#C0392B"}},
    ]

    # 2. 综合得分 10 分一档分箱直方图 (FR-02-05)
    bins = [f"{i}~{i+10}" for i in range(0, 100, 10)]
    bin_counts = [0] * 10
    for s in Enterprise.objects.values_list("score_total", flat=True):
        idx = min(int(float(s) // 10), 9)
        bin_counts[max(0, idx)] += 1

    # 3. 各企业类型的四维度平均分对比 (FR-02-06)
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
    """FR-02-07: 单个企业四维度得分与同类型企业均值雷达图对比"""
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

    return render(request, "chart_compare.html", {
        "samples": samples,
        "ent": ent,
        "ent_scores_json": json.dumps(ent_scores),
        "avg_scores_json": json.dumps(avg_scores),
    })
