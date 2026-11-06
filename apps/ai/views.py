import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from apps.accounts.decorators import login_required_custom
from services.llm_predict import predict_enterprise_risk
from services.nlp_infer import analyze_risk_text, check_nlp_health

@login_required_custom
def predict_page(request):
    return render(request, "predict.html")

@require_http_methods(["POST"])
@login_required_custom
def predict_api(request):
    """表 3-3: POST /predict/api/ 大模型预估接口"""
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
    return JsonResponse({"code": 0, "data": res})

@login_required_custom
def model_show(request):
    return render(request, "model_show.html")

@require_http_methods(["POST"])
@login_required_custom
def model_analyze_api(request):
    """FR-05-01: POST /model/analyze/ 文本识别接口"""
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
    """FR-05-02: GET /model/health/ 服务探活"""
    return JsonResponse(check_nlp_health())
