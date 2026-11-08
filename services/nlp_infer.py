import os
import time
import jieba
import requests

RISK_LEXICON = {
    "财务": ["欠税", "逾期", "违约", "破产", "资不抵债", "坏账", "抽逃出资", "拖欠", "亏损", "冻结"],
    "经营": ["停业", "歇业", "注销", "吊销", "异常名录", "虚开发票", "停产", "裁员", "搬迁", "纠纷"],
    "合规": ["立案", "败诉", "行政处罚", "罚款", "失信", "限高", "传票", "起诉", "违法", "违规"],
    "质量": ["被执行", "强制执行", "召回", "不合格", "事故", "投诉", "赔偿", "查封", "扣押", "退货"],
}

def check_nlp_health() -> dict:
    """FR-05-02: 探活 /health 接口"""
    base_url = os.environ.get("NLP_SERVICE_URL", "http://127.0.0.1:8001")
    try:
        r = requests.get(f"{base_url}/health", timeout=2)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"status": "ok", "model_loaded": True, "version": "1.0.0-local", "mode": "内置轻量引擎"}

def analyze_risk_text(text: str, model: str = "general") -> dict:
    """FR-05-01: 文本风险识别（长度 1~2000 字，超长截断并置 truncated:true）"""
    t0 = time.time()
    model_type = model if model in ("general", "finance", "compliance") else "general"
    truncated = len(text) > 2000
    clean_text = text[:2000]

    base_url = os.environ.get("NLP_SERVICE_URL", "http://127.0.0.1:8001")
    try:
        r = requests.post(
            f"{base_url}/analyze",
            json={"text": clean_text, "model": model_type},
            timeout=5,
        )
        if r.status_code == 200:
            body = r.json()
            if body.get("code") == 0 and "data" in body:
                body["data"]["truncated"] = truncated
                return body["data"]
    except Exception:
        pass

    # 本地 jieba 分词 + 风险词库计算
    words = list(jieba.cut(clean_text))
    hits = []
    scores = {"财务": 25.0, "经营": 25.0, "合规": 25.0, "质量": 25.0}

    for cat, kw_list in RISK_LEXICON.items():
        for kw in kw_list:
            cnt = clean_text.count(kw) if len(kw) > 2 else words.count(kw)
            if cnt > 0:
                hits.append({"word": kw, "category": cat, "count": cnt})
                weight = 2.5 if (model_type == "finance" and cat == "财务") or (model_type == "compliance" and cat == "合规") else 1.5
                scores[cat] = max(0.0, round(scores[cat] - cnt * weight, 2))

    total = round(sum(scores.values()), 1)
    level = "低" if total >= 80 else ("中" if total >= 50 else "高")
    return {
        "scores": scores,
        "total_score": total,
        "hits": hits,
        "level": level,
        "truncated": truncated,
        "elapsed_ms": max(1, int((time.time() - t0) * 1000)),
    }
