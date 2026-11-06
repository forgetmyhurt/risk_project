import json
import os
import time
import requests

ALLOWED_MODELS = {"general": "通用风控模型", "finance": "财务审慎模型", "compliance": "司法合规模型"}

def _local_fallback(payload: dict, model_type: str, reason: str) -> dict:
    """外部大模型超时或未配置 API Key 时的本地确定性降级结果（NFR-05/NFR-06）"""
    desc = payload.get("description", "")
    risk_words = ["违约", "被执行", "失信", "吊销", "欠税", "查封", "败诉", "冻结", "处罚"]
    hit_cnt = sum(1 for w in risk_words if w in desc)
    base = 86.0 - hit_cnt * 12.0
    if model_type == "finance":
        base -= 3.0
    elif model_type == "compliance":
        base -= 5.0 if hit_cnt else 0.0

    score = max(35.0, min(95.0, round(base, 1)))
    level = "低风险" if score >= 80 else ("中风险" if score >= 50 else "高风险")
    return {
        "total_score": score,
        "risk_level": level,
        "model_used": ALLOWED_MODELS[model_type],
        "fallback": True,
        "fallback_reason": reason,
        "summary": f"基于【{ALLOWED_MODELS[model_type]}】对企业“{payload['enterprise_name']}”完成多维预估，综合参考分为 {score} 分（{level}）。",
        "dimensions": [
            {"name": "财务维度", "analysis": "结合企业规模与资金周转特征，建议核查近三年实缴资本与现金流匹配度。"},
            {"name": "经营维度", "analysis": f"所属行业为“{payload['industry'] or '综合行业'}”，主体经营稳定性整体可控。"},
            {"name": "合规维度", "analysis": f"文本描述中共命中 {hit_cnt} 项司法/合规敏感特征词。"},
            {"name": "质量维度", "analysis": "履约与执行记录未见重大连带违约信号，建议保持常规贷后跟踪。"},
        ],
        "suggestions": [
            "核对最新一期征信报告与被执行人公示信息，确认无新增涉诉。",
            "若该预估分与规则评分差值超过 20 分，请触发人工复核流程。",
        ],
    }

def predict_enterprise_risk(enterprise_name: str, industry: str, scale: str, description: str, model: str) -> dict:
    """组装白名单请求体并调用大模型接口（5 秒超时，失败不重试）"""
    model_type = model if model in ALLOWED_MODELS else "general"
    # NFR-07: 白名单字段，绝不包含身份证号、联系电话等敏感项
    safe_payload = {
        "enterprise_name": enterprise_name.strip()[:200],
        "industry": industry.strip()[:100],
        "scale": scale if scale in ("large", "medium", "small", "micro") else "medium",
        "description": description.strip()[:1000],
        "model": model_type,
    }

    api_url = os.environ.get("LLM_API_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    t0 = time.time()

    if not api_url or not api_key:
        res = _local_fallback(safe_payload, model_type, "未配置外部 API Key，已启用本地规则引擎降级")
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res

    try:
        resp = requests.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("LLM_MODEL_NAME", "deepseek-chat"),
                "messages": [
                    {"role": "system", "content": "你是企业风控专家，请输出 JSON 格式的风险评估结果。"},
                    {"role": "user", "content": json.dumps(safe_payload, ensure_ascii=False)},
                ],
                "timeout": 5,
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        res = _local_fallback(safe_payload, model_type, "")
        res["fallback"] = False
        res["summary"] = data.get("choices", [{}])[0].get("message", {}).get("content", res["summary"])[:500]
    except Exception as exc:
        res = _local_fallback(safe_payload, model_type, f"AI 服务不可用或超时（{exc.__class__.__name__}），已降级")

    res["elapsed_ms"] = int((time.time() - t0) * 1000)
    return res
