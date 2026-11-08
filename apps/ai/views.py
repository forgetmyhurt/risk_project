import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from apps.accounts.decorators import login_required_custom
from apps.accounts.models import UserActivityLog, log_activity
from apps.enterprise.models import Enterprise
from services.llm_predict import chat_with_risk_copilot, predict_enterprise_risk
from services.nlp_infer import analyze_risk_text, check_nlp_health

LEVEL_CN = {"L": "低风险", "M": "中风险", "H": "高风险"}

@login_required_custom
def predict_page(request):
    return render(request, "predict.html")

@require_http_methods(["POST"])
@login_required_custom
def predict_api(request):
    name = request.POST.get("enterprise_name", "").strip()
    if not name:
        return JsonResponse({"code": -1, "message": "企业名称不能为空"}, status=400)
    res = predict_enterprise_risk(
        enterprise_name=name,
        industry=request.POST.get("industry", ""),
        scale=request.POST.get("scale", "medium"),
        description=request.POST.get("description", ""),
        model=request.POST.get("model", "general"),
    )
    log_activity(request, UserActivityLog.ActionType.SCORE, f"调用 AI 风险预估：{name}")
    return JsonResponse({"code": 0, "data": res})

@require_http_methods(["POST"])
@login_required_custom
def copilot_chat_api(request):
    """迭代点1：右侧 AI 问答辅助评估侧边栏对话接口"""
    question = request.POST.get("question", "").strip()
    ent_id = request.POST.get("enterprise_id", "").strip()
    model_type = request.POST.get("model", "general").strip()

    if not question:
        return JsonResponse({"code": -1, "message": "请输入您要咨询的风险问题"}, status=400)

    ent_ctx = None
    ent = None
    if ent_id.isdigit():
        ent = Enterprise.objects.filter(pk=int(ent_id)).first()
    elif ent_id:
        ent = Enterprise.objects.filter(firm_name__icontains=ent_id).first()

    if ent:
        ind = ent.indicators.filter(is_current=True).first()
        ent_ctx = {
            "id": ent.id,
            "firm_name": ent.firm_name,
            "industry": ent.ind_econ_name or ent.firm_type or "综合",
            "reg_cap": float(ent.reg_cap),
            "ope_status": ent.get_ope_status_display(),
            "score_total": float(ent.score_total),
            "risk_level_cn": LEVEL_CN.get(ent.risk_level, "低风险"),
            "score_fin": float(ind.score_fin) if ind else 25.0,
            "score_ope": float(ind.score_ope) if ind else 25.0,
            "score_com": float(ind.score_com) if ind else 25.0,
            "score_qua": float(ind.score_qua) if ind else 25.0,
            "cai": f"{ind.cai_1}/{ind.cai_2}/{ind.cai_3}" if ind else "0/0/0",
            "s_an": f"{ind.s_an_1}/{ind.s_an_2}/{ind.s_an_3}" if ind else "0/0/0",
            "li_an": f"{ind.li_an_1}/{ind.li_an_2}/{ind.li_an_3}" if ind else "0/0/0",
            "zhi": f"{ind.zhi_1}/{ind.zhi_2}/{ind.zhi_3}" if ind else "0/0/0",
        }

    sandbox_raw = request.POST.get("sandbox_ctx", "").strip()
    if ent_ctx and sandbox_raw:
        try:
            sb = json.loads(sandbox_raw)
            ent_ctx["sandbox"] = sb
        except Exception:
            pass
    data = chat_with_risk_copilot(question, ent_ctx=ent_ctx, model_type=model_type)
    if ent_ctx:
        data["bound_enterprise"] = {
            "id": ent_ctx["id"],
            "name": ent_ctx["firm_name"],
            "score": ent_ctx["score_total"],
            "level": ent_ctx["risk_level_cn"],
        }
    return JsonResponse({"code": 0, "data": data})

@login_required_custom
def model_show(request):
    return render(request, "model_show.html")

@require_http_methods(["POST"])
@login_required_custom
def model_analyze_api(request):
    text = request.POST.get("text", "").strip()
    model = request.POST.get("model", "general").strip()
    if not text and request.body:
        try:
            body = json.loads(request.body)
            text = str(body.get("text", "")).strip()
            model = str(body.get("model", "general")).strip()
        except Exception:
            pass
    if not text:
        return JsonResponse({"code": 40001, "message": "待分析文本不能为空"}, status=400)
    data = analyze_risk_text(text, model)
    return JsonResponse({"code": 0, "data": data})

@require_http_methods(["GET"])
def model_health_api(request):
    return JsonResponse(check_nlp_health())


@require_http_methods(["GET"])
@login_required_custom
def enterprise_corpus_api(request):
    """提取指定企业的经营范围、工商状态与涉诉记录，合成待扫描尽调文本"""
    ent_q = request.GET.get("enterprise_id", "").strip()
    ent = None
    if ent_q.isdigit():
        ent = Enterprise.objects.filter(pk=int(ent_q)).first()
    elif ent_q:
        ent = Enterprise.objects.filter(firm_name__icontains=ent_q).first()

    if not ent:
        return JsonResponse({"code": -1, "message": "未找到对应企业，请先进入企业详情页或在上方绑定企业名称"}, status=404)

    ind = ent.indicators.filter(is_current=True).first()
    status_text = ent.get_ope_status_display()

    # 依据真实涉诉次数合成客观尽调摘录（若为0则生成“无XX记录”以测试NLP否定语义识别能力）
    judicial_parts = []
    if ind:
        cai_sum = ind.cai_1 + ind.cai_2 + ind.cai_3
        lian_sum = ind.li_an_1 + ind.li_an_2 + ind.li_an_3
        zhi_sum = ind.zhi_1 + ind.zhi_2 + ind.zhi_3

        judicial_parts.append(
            f"近三年累计发生被裁判文书 {cai_sum} 起（涉及合同违约或败诉争议）" if cai_sum > 0 else "近三年无合同违约及败诉裁判记录"
        )
        judicial_parts.append(
            f"存在作为被告被立案调查记录 {lian_sum} 次" if lian_sum > 0 else "未发生被立案调查或行政处罚情形"
        )
        judicial_parts.append(
            f"存在被法院强制执行记录 {zhi_sum} 次（需排查查封冻结风险）" if zhi_sum > 0 else "名下无被执行人及查封冻结记录"
        )

    corpus = (
        f"【主体状态】企业名称为{ent.firm_name}，当前登记经营状态为{status_text}，所属行业为{ent.ind_econ_name or '综合行业'}。\n"
        f"【经营范围】{ent.business_scope or '未登记具体经营范围'}。\n"
        f"【司法与合规核查】{'；'.join(judicial_parts)}。"
    )
    return JsonResponse({
        "code": 0,
        "data": {
            "firm_name": ent.firm_name,
            "corpus": corpus,
        },
    })
