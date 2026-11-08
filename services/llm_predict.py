# -*- coding: utf-8 -*-
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import requests

ALLOWED_MODELS = {"general": "通用风控模型", "finance": "财务审慎模型", "compliance": "司法合规模型"}
LEVEL_CN = {"L": "低风险", "M": "中风险", "H": "高风险"}
LOCAL_PKL_PATH = Path(__file__).resolve().parent / "local_risk_model.pkl"

_LOCAL_BUNDLE = None
# 轻量多轮对话记忆池（按企业ID缓存最近 3 轮问答，赋予前端上下文连续对话能力）
_CHAT_HISTORY_CACHE: dict[str, list[dict]] = {}


def _get_local_ml_bundle():
    global _LOCAL_BUNDLE
    if _LOCAL_BUNDLE is None and LOCAL_PKL_PATH.exists():
        try:
            _LOCAL_BUNDLE = joblib.load(LOCAL_PKL_PATH)
        except Exception:
            _LOCAL_BUNDLE = None
    return _LOCAL_BUNDLE


def _extract_12_features(ent_ctx: dict) -> list[int]:
    vec = []
    for key in ("cai", "s_an", "li_an", "zhi"):
        parts = str(ent_ctx.get(key, "0/0/0")).split("/")
        for i in range(3):
            try:
                vec.append(int(float(parts[i])))
            except (IndexError, ValueError):
                vec.append(0)
    return vec


def _call_local_ollama(ent_ctx: Optional[dict], question: str, model_type: str) -> tuple[str, str]:
    """
    人性化问答调用逻辑：
    1. 将企业背景放入 system 角色，避免触发 user 消息的 SFT 模板死板过拟合
    2. user 角色直接传递用户自然提问，保留多轮对话上下文
    """
    ollama_url = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/chat").strip()
    ollama_model = os.environ.get("LOCAL_LLM_MODEL", "verity").strip()
    mode_name = ALLOWED_MODELS.get(model_type, "通用风控模型")

    if ent_ctx:
        sys_prompt = (
            f"你是专业的银行信贷与企业尽调 AI 顾问（当前采用：{mode_name}）。\n"
            f"你正在协助风控人员评估【{ent_ctx['firm_name']}】，以下是你已掌握的该企业实时工商与风控底稿：\n"
            f"- 所属行业：{ent_ctx['industry']}，经营状态：{ent_ctx['ope_status']}，注册资本：{ent_ctx['reg_cap']}万元\n"
            f"- 综合风险得分：{ent_ctx['score_total']}分（评级：{ent_ctx['risk_level_cn']}，满分100分，≥80低风险，50~79中风险，<50高风险）\n"
            f"- 四维得分明细（各满分25分）：财务维度 {ent_ctx['score_fin']}分、经营维度 {ent_ctx['score_ope']}分、"
            f"合规维度 {ent_ctx['score_com']}分、质量维度 {ent_ctx['score_qua']}分\n"
            f"- 近1/2/3年司法涉诉原始次数：被裁判({ent_ctx['cai']})次、涉案立案({ent_ctx['s_an']})次、"
            f"被立案({ent_ctx['li_an']})次、被执行({ent_ctx['zhi']})次\n\n"
            "【回答要求】：\n"
            "1. 请像真人风控专家一样，直接、自然、有条理地回答用户的具体问题（不要只背诵一句得分，也不要输出JSON代码）。\n"
            "2. 如果用户问你叫什么或打招呼，请自然介绍自己是企业风控AI助手Verity，并顺带提及当前正在协助分析该企业。\n"
            "3. 如果用户询问能否放贷、短板原因或风控建议，请结合上述四维得分、最薄弱维度及涉诉次数给出具体的分析理由和授信准入建议（如额度控制、追加担保、核查结案证明等）。"
        )
        cache_key = f"ent_{ent_ctx['id']}"
    else:
        sys_prompt = (
            f"你是专业的银行信贷与企业尽调 AI 顾问（{mode_name}）。"
            "请用自然、专业、人性化的中文与用户对话，解答企业风险评估与信贷尽调相关问题。"
        )
        cache_key = "global"

    # 组装带上下文记忆的 messages（保留最近 10 轮对话）
    history = _CHAT_HISTORY_CACHE.get(cache_key, [])[-20:]
    messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": question}]

    try:
        r = requests.post(
            ollama_url,
            json={
                "model": ollama_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.55,      # 适度提高温度，恢复自然流畅的对话语气
                    "top_p": 0.9,
                    "repeat_penalty": 1.15,   # 防止复读机式重复短句
                    "num_predict": 512,
                },
            },
            timeout=25,
        )
        if r.status_code == 200:
            content = r.json().get("message", {}).get("content", "").strip()
            if content:
                # 若微调过度导致特定问题只吐出1句过短的话，自动触发二次追问补全细节
                if ent_ctx and len(content) < 42 and any(k in question for k in ["放贷", "放款", "授信", "建议", "薄弱", "分析", "怎么样"]):
                    follow_up_q = (
                        f"请针对问题“{question}”，结合{ent_ctx['firm_name']}的综合得分({ent_ctx['score_total']}分/{ent_ctx['risk_level_cn']})、"
                        f"财务({ent_ctx['score_fin']})/经营({ent_ctx['score_ope']})/合规({ent_ctx['score_com']})/质量({ent_ctx['score_qua']})四维表现，"
                        "分点详细说明原因，并给出具体的信贷准入与风控缓释措施。"
                    )
                    r2 = requests.post(
                        ollama_url,
                        json={
                            "model": ollama_model,
                            "messages": [
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": follow_up_q},
                            ],
                            "stream": False,
                            "options": {"temperature": 0.6, "repeat_penalty": 1.18, "num_predict": 512},
                        },
                        timeout=25,
                    )
                    if r2.status_code == 200:
                        content2 = r2.json().get("message", {}).get("content", "").strip()
                        if len(content2) > len(content):
                            content = content2

                # 写入多轮对话缓存
                history.extend([
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": content},
                ])
                _CHAT_HISTORY_CACHE[cache_key] = history[-6:]
                return content, f"Ollama 本地微调大模型 ({ollama_model})"
    except Exception as exc:
        print(f"[AI侧边栏] Ollama 调用异常: {exc}")

    return "", ""


def _infer_with_local_ml_model(question: str, ent_ctx: Optional[dict], model_type: str) -> tuple[str, str]:
    """当 Ollama 未启动时的降级兜底：本地自训练随机森林与意图模型 (.pkl)"""
    bundle = _get_local_ml_bundle()
    if not bundle:
        return "", ""

    intent_clf = bundle["intent_clf"]
    rf_model = bundle["rf_model"]
    feat_names = bundle["feature_names_cn"]

    probs = intent_clf.predict_proba([question])[0]
    best_idx = int(np.argmax(probs))
    intent = intent_clf.classes_[best_idx]
    intent_conf = float(probs[best_idx]) * 100

    if not ent_ctx:
        return (
            f"您好！我是企业风险评估 AI 助手（{ALLOWED_MODELS[model_type]}）。"
            "请进入任意【企业详情页】呼出侧边栏，我将结合该企业的 12 项风险指标为您解答。",
            f"本地自训练模型({bundle['version']})",
        )

    x_vec = np.array([_extract_12_features(ent_ctx)], dtype=np.float32)
    rf_probs = rf_model.predict_proba(x_vec)[0]
    p_high = float(rf_probs[2]) * 100 if len(rf_probs) > 2 else 0.0

    importances = rf_model.feature_importances_
    contributions = x_vec[0] * importances
    top_indices = np.argsort(contributions)[::-1][:3]
    top_factors = [
        f"{feat_names[i]}({int(x_vec[0][i])}次, 权重{importances[i]*100:.1f}%)"
        for i in top_indices if x_vec[0][i] > 0
    ]
    factor_str = "、".join(top_factors) if top_factors else "12项涉诉与执行指标均为0"

    reply = (
        f"针对【{ent_ctx['firm_name']}】，目前综合得分为 **{ent_ctx['score_total']} 分（{ent_ctx['risk_level_cn']}）**，"
        f"随机森林评估其高危概率为 **{p_high:.1f}%**。\n"
        f"主要扣分与风险因子集中在：{factor_str}。建议结合具体涉诉文书进一步核查。"
    )
    return reply, f"本地自训练模型({bundle['version']}) · 意图:{intent}({intent_conf:.0f}%)"


def chat_with_risk_copilot(question: str, ent_ctx: Optional[dict] = None, model_type: str = "general") -> dict:
    t0 = time.time()
    q = question.strip()[:500]
    m_type = model_type if model_type in ALLOWED_MODELS else "general"

    # 第一级：云端 API（仅在配置了外部 Key 时启用）
    api_url = os.environ.get("LLM_API_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if api_url and api_key:
        try:
            resp = requests.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": os.environ.get("LLM_MODEL_NAME", "deepseek-chat"),
                    "messages": [{"role": "user", "content": q}],
                },
                timeout=8,
            )
            resp.raise_for_status()
            reply = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if reply:
                return {
                    "reply": reply,
                    "engine": "云端大模型 API",
                    "fallback": False,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                }
        except Exception:
            pass

    # 第二级：调用本地 Ollama 微调大模型（不再拼接死板头部，直接返回自然对话内容）
    ollama_reply, ollama_badge = _call_local_ollama(ent_ctx, q, m_type)
    if ollama_reply:
        return {
            "reply": ollama_reply,
            "engine": ollama_badge,
            "fallback": False,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    # 第三级：本地机器学习模型兜底
    ml_reply, ml_badge = _infer_with_local_ml_model(q, ent_ctx, m_type)
    if ml_reply:
        return {
            "reply": ml_reply,
            "engine": ml_badge,
            "fallback": True,
            "elapsed_ms": max(1, int((time.time() - t0) * 1000)),
        }

    return {
        "reply": "本地 Ollama 与机器学习模型均未就绪，请检查 Ollama 服务是否已启动。",
        "engine": "静态规则兜底",
        "fallback": True,
        "elapsed_ms": max(1, int((time.time() - t0) * 1000)),
    }


def predict_enterprise_risk(enterprise_name: str, industry: str, scale: str, description: str, model: str) -> dict:
    model_type = model if model in ALLOWED_MODELS else "general"
    t0 = time.time()
    chat_res = chat_with_risk_copilot(
        question=f"请对企业【{enterprise_name}】（行业：{industry}，近况：{description}）进行风险评估并给出风控建议。",
        ent_ctx=None,
        model_type=model_type,
    )
    risk_words = ["违约", "被执行", "失信", "吊销", "欠税", "查封", "败诉", "冻结", "处罚"]
    hit_cnt = sum(1 for w in risk_words if w in description)
    score = max(35.0, min(95.0, round(86.0 - hit_cnt * 12.0, 1)))
    level = "低风险" if score >= 80 else ("中风险" if score >= 50 else "高风险")
    return {
        "total_score": score,
        "risk_level": level,
        "model_used": chat_res.get("engine", "verity"),
        "fallback": chat_res.get("fallback", False),
        "fallback_reason": f"当前推理引擎：{chat_res.get('engine')}",
        "summary": chat_res["reply"],
        "dimensions": [],
        "suggestions": [],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
