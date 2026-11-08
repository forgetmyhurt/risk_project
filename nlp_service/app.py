from flask import Flask, jsonify, request
import jieba

app = Flask(__name__)

RISK_LEXICON = {
    "财务": ["欠税", "逾期", "违约", "破产", "资不抵债", "坏账", "抽逃出资", "拖欠", "亏损", "冻结"],
    "经营": ["停业", "歇业", "注销", "吊销", "异常名录", "虚开发票", "停产", "裁员", "搬迁", "纠纷"],
    "合规": ["立案", "败诉", "行政处罚", "罚款", "失信", "限高", "传票", "起诉", "违法", "违规"],
    "质量": ["被执行", "强制执行", "召回", "不合格", "事故", "投诉", "赔偿", "查封", "扣押", "退货"],
}

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model_loaded": True, "version": "1.0.0-container"})

@app.route("/analyze", methods=["POST"])
def analyze():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", "")).strip()[:2000]
    model_type = body.get("model", "general")
    if not text:
        return jsonify({"code": 400, "message": "待分析文本不能为空"}), 400

    words = list(jieba.cut(text))
    hits = []
    scores = {"财务": 25.0, "经营": 25.0, "合规": 25.0, "质量": 25.0}

    for cat, kw_list in RISK_LEXICON.items():
        for kw in kw_list:
            cnt = text.count(kw) if len(kw) > 2 else words.count(kw)
            if cnt > 0:
                hits.append({"word": kw, "category": cat, "count": cnt})
                weight = 2.5 if (model_type == "finance" and cat == "财务") or (model_type == "compliance" and cat == "合规") else 1.5
                scores[cat] = max(0.0, round(scores[cat] - cnt * weight, 2))

    total = round(sum(scores.values()), 1)
    level = "低" if total >= 80 else ("中" if total >= 50 else "高")
    return jsonify({
        "code": 0,
        "data": {
            "scores": scores,
            "total_score": total,
            "hits": hits,
            "level": level,
            "truncated": len(body.get("text", "")) > 2000,
            "elapsed_ms": 12
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
