from flask import Flask, jsonify, request
import jieba

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"status": "ok", "model_loaded": True, "version": "1.0.0"})

@app.post("/analyze")
def analyze():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", "")).strip()
    if not text:
        return jsonify({"code": 400, "msg": "空文本"}), 400
    # 与主站契约保持一致
    from services.nlp_infer import analyze_risk_text
    return jsonify({"code": 0, "data": analyze_risk_text(text, body.get("model", "general"))})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
