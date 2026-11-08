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


def _build_sandbox_deep_analysis(ent_ctx: dict, sb: dict, llm_raw_text: str) -> str:
    """
    当检测到用户正在进行沙箱推演（What-If）时，结合大模型输出与沙箱真实指标增量，
    生成具有实战风控价值的【沙箱整改可行性与授信准入评估报告】，彻底解决微调模型机械背分问题。
    """
    name = ent_ctx["firm_name"]
    base_s = sb.get("base_score", ent_ctx["score_total"])
    sim_s = sb.get("sim_score", base_s)
    base_lvl = sb.get("base_level", ent_ctx["risk_level_cn"])
    sim_lvl = sb.get("sim_level", base_lvl)
    diff_str = sb.get("diff_text", "")
    changes = sb.get("changes_list", [])
    change_str = "；".join(changes) if changes else "未发生指标变动"

    # 识别演练方向（风险缓释修复 vs 风险恶化压力测试）
    is_improve = sim_s >= base_s

    if is_improve:
        if sim_s >= 80:
            credit_rule = "**可由审慎/拦截通道转入【标准授信通道】**，建议按正常敞口核定额度，免除额外保证金。"
        elif sim_s >= 50:
            credit_rule = "**满足【有条件审慎准入】底线**，建议授信敞口控制在常规额度的 60%~70%，并追加实控人连带责任保证。"
        else:
            credit_rule = "**即便完成上述整改，得分（" + str(sim_s) + "分）仍低于 50 分红线**，尚不具备放款条件，需进一步削减立案与被执行存量。"

        report = (
            f"🧪 **【{name}】沙箱推演（What-If）可行性与授信准入评估**\n\n"
            f"**1. 演练前后评级跃迁对比**\n"
            f"• **得分变化**：由真实基线 **{base_s}分（{base_lvl}）** 跃升至 **{sim_s}分（{sim_lvl}，{diff_str}）**。\n"
            f"• **演练后四维结构**：财务 **{sb.get('score_fin')}** / 经营 **{sb.get('score_ope')}** / 合规 **{sb.get('score_com')}** / 质量 **{sb.get('score_qua')}**（满分各25分）。\n"
            f"• **核心调整项**：`{change_str}`。\n\n"
            f"**2. 整改方案落地可行性核验清单（放款前提条件）**\n"
            f"• **司法执行结清核验**：沙箱中下调的被执行/被裁判指标，在现实业务中**不可仅凭企业口头承诺认定**，必须要求企业提供法院出具的《结案通知书》、《执行完毕证明》或与申请执行人签署的《执行和解协议》及银行付款水单。\n"
            f"• **征信与公网更新时滞**：司法数据从履行完毕到公开网撤销通常存在 15~30 天滞后期，放款前须由法务专员人工核验原件。\n\n"
            f"**3. 演练后授信审批结论**\n"
            f"• {credit_rule}"
        )
    else:
        report = (
            f"⚠️ **【{name}】沙箱极端压力测试（Stress Test）预警评估**\n\n"
            f"**1. 压力冲击下评级劣化幅度**\n"
            f"• **得分变化**：由基线 **{base_s}分（{base_lvl}）** 下挫至 **{sim_s}分（{sim_lvl}，{diff_str}）**。\n"
            f"• **演练后四维得分**：财务 **{sb.get('score_fin')}** / 经营 **{sb.get('score_ope')}** / 合规 **{sb.get('score_com')}** / 质量 **{sb.get('score_qua')}**。\n"
            f"• **冲击因子**：`{change_str}`。\n\n"
            f"**2. 抗风险韧性与贷后应急预案**\n"
            f"• **安全边际研判**：{'该企业在承受新增涉诉冲击后已跌破风险阈值，抗风险安全垫极薄。' if sim_s < 80 else '该企业在承受压力冲击后仍维持低风险区间，主体韧性较强。'}\n"
            f"• **风控触发机制**：建议在授信合同中设置**交叉违约与提前到期条款**——一旦贷后监测到实际新增指标达到本次沙箱压力值，立即中止未提款额度并启动账户冻结保全。"
        )

    # 若本地大模型额外生成了非纯背诵的有价值建议，附在底部作为补充
    if llm_raw_text and not (llm_raw_text.startswith(name) and "综合风险得分为" in llm_raw_text and len(llm_raw_text) < 160):
        report += f"\n\n💡 **大模型补充洞察**：{llm_raw_text}"

    return report


def _call_local_ollama(ent_ctx: Optional[dict], question: str, model_type: str) -> tuple[str, str]:
    ollama_url = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/chat").strip()
    ollama_model = os.environ.get("LOCAL_LLM_MODEL", "verity").strip()
    mode_name = ALLOWED_MODELS.get(model_type, "通用风控模型")
    sb = ent_ctx.get("sandbox") if ent_ctx else None

    if ent_ctx:
        # 若携带了沙箱上下文，将沙箱演练后的真实四维得分注入系统提示词，防止模型拿旧数据胡说
        active_total = sb["sim_score"] if sb else ent_ctx["score_total"]
        active_lvl = sb["sim_level"] if sb else ent_ctx["risk_level_cn"]
        active_fin = sb["score_fin"] if sb else ent_ctx["score_fin"]
        active_ope = sb["score_ope"] if sb else ent_ctx["score_ope"]
        active_com = sb["score_com"] if sb else ent_ctx["score_com"]
        active_qua = sb["score_qua"] if sb else ent_ctx["score_qua"]

        sys_prompt = (
            f"你是专业的银行信贷与企业尽调 AI 顾问（当前采用：{mode_name}）。\n"
            f"当前评估企业：【{ent_ctx['firm_name']}】，行业：{ent_ctx['industry']}，经营状态：{ent_ctx['ope_status']}，注册资本：{ent_ctx['reg_cap']}万元。\n"
            f"当前综合风险得分：{active_total}分（{active_lvl}），四维得分：财务{active_fin}/经营{active_ope}/合规{active_com}/质量{active_qua}。\n"
            "请直接针对用户的问题给出具体的风控判断、原因剖析与授信建议，严禁只背诵一遍企业得分！"
        )
        cache_key = f"ent_{ent_ctx['id']}"
    else:
        sys_prompt = f"你是专业的银行信贷与企业尽调 AI 顾问（{mode_name}），请用自然专业的中文解答风控问题。"
        cache_key = "global"

    history = _CHAT_HISTORY_CACHE.get(cache_key, [])[-4:]
    messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": question}]

    try:
        r = requests.post(
            ollama_url,
            json={
                "model": ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.55, "top_p": 0.9, "repeat_penalty": 1.18, "num_predict": 512},
            },
            timeout=25,
        )
        if r.status_code == 200:
            content = r.json().get("message", {}).get("content", "").strip()
            # 若是沙箱推演提问，调用深度对比分析合成器，彻底根除图1中无意义的背分回答
            if ent_ctx and (sb or "沙箱" in question):
                effective_sb = sb or {
                    "base_score": ent_ctx["score_total"],
                    "sim_score": ent_ctx["score_total"],
                    "base_level": ent_ctx["risk_level_cn"],
                    "sim_level": ent_ctx["risk_level_cn"],
                    "diff_text": "±0.0分",
                    "score_fin": ent_ctx["score_fin"],
                    "score_ope": ent_ctx["score_ope"],
                    "score_com": ent_ctx["score_com"],
                    "score_qua": ent_ctx["score_qua"],
                    "changes_list": ["沙箱模拟调整"],
                }
                content = _build_sandbox_deep_analysis(ent_ctx, effective_sb, content)

            if content:
                history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": content}])
                _CHAT_HISTORY_CACHE[cache_key] = history[-4:]
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
