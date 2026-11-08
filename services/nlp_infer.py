# -*- coding: utf-8 -*-
"""
NLP 文本风险识别引擎 2.0
支持：1. 五维风控与受限行业词典  2. 上下文否定/缓释语义感知  3. 分句级风险溯源
"""
import os
import re
import time
import requests

# 五维风控词典：(风险词, 所属类别, 基础扣分权重)
RISK_LEXICON = [
    # 司法执行类
    ("失信被执行", "司法执行", 18.0),
    ("被执行人", "司法执行", 14.0),
    ("被执行", "司法执行", 12.0),
    ("强制执行", "司法执行", 14.0),
    ("限制高消费", "司法执行", 15.0),
    ("限高", "司法执行", 12.0),
    ("终本案件", "司法执行", 16.0),
    ("查封", "司法执行", 12.0),
    ("冻结", "司法执行", 12.0),
    ("司法拍卖", "司法执行", 15.0),
    ("败诉", "司法执行", 10.0),
    # 行政合规类
    ("吊销", "行政合规", 22.0),
    ("严重违法", "行政合规", 18.0),
    ("立案调查", "行政合规", 14.0),
    ("被立案", "行政合规", 11.0),
    ("行政处罚", "行政合规", 10.0),
    ("经营异常", "行政合规", 10.0),
    ("环保处罚", "行政合规", 9.0),
    ("停产整顿", "行政合规", 15.0),
    ("非法集资", "行政合规", 25.0),
    # 财务流动性类
    ("欠税", "财务风险", 13.0),
    ("破产重整", "财务风险", 22.0),
    ("破产清算", "财务风险", 25.0),
    ("资不抵债", "财务风险", 20.0),
    ("资金链断裂", "财务风险", 20.0),
    ("逾期", "财务风险", 12.0),
    ("欠薪", "财务风险", 12.0),
    ("抽逃出资", "财务风险", 16.0),
    # 经营违约类
    ("合同违约", "经营违约", 11.0),
    ("违约", "经营违约", 9.0),
    ("拒不履行", "经营违约", 15.0),
    ("拖欠货款", "经营违约", 11.0),
    ("股权质押", "经营违约", 8.0),
    ("连带担保", "经营违约", 9.0),
    ("连带责任", "经营违约", 8.0),
    # 经营范围受限/高危行业关注类
    ("民间借贷", "受限行业", 12.0),
    ("小额贷款", "受限行业", 8.0),
    ("融资担保", "受限行业", 10.0),
    ("非融资性担保", "受限行业", 12.0),
    ("典当", "受限行业", 9.0),
    ("寄售", "受限行业", 8.0),
    ("危险化学品", "受限行业", 8.0),
    ("易燃易爆", "受限行业", 8.0),
    ("虚拟货币", "受限行业", 18.0),
]

# 前序否定词（出现在风险词前 6 个字符内，判定为“未发生/已排除”）
PRE_NEGATION_PATTERNS = re.compile(
    r"(无|未见|未发生|未发现|不存在|并无|均无|未曾|没有|未有|0起|零)"
)
# 后序缓释/结清词（出现在风险词后 12 个字符内，判定为“已结清/已缓释”）
POST_MITIGATION_PATTERNS = re.compile(
    r"(已结清|已全部结清|已结案|已履行完毕|已撤诉|已解除|已移出|已撤销|已修复|完毕)"
)


def _split_sentences(text: str) -> list[str]:
    """按中文标点符号将长文本切分为独立子句"""
    raw = re.split(r"[。；;！!\n]+", text)
    return [s.strip() for s in raw if s and s.strip()]


def analyze_risk_text(text: str, model: str = "general") -> dict:
    """
    NLP 2.0 语义风险识别：
    1. 分句扫描五维风险词
    2. 检测前后文否定与缓释窗口，区分 active_hits（实锤扣分）与 negated_hits（已排除/缓释）
    3. 输出分句级风险溯源列表与综合风险评分
    """
    t0 = time.time()
    clean_text = (text or "").strip()[:2000]
    if not clean_text:
        return {
            "total_score": 100.0,
            "level": "低",
            "hits": [],
            "negated_hits": [],
            "sentence_analysis": [],
            "summary": "输入文本为空",
            "elapsed_ms": 1,
        }

    # 不同模型侧重的类别权重乘子
    cat_multiplier = {
        "司法执行": 1.25 if model == "compliance" else 1.0,
        "行政合规": 1.25 if model == "compliance" else 1.0,
        "财务风险": 1.30 if model == "finance" else 1.0,
        "经营违约": 1.15 if model == "finance" else 1.0,
        "受限行业": 1.0,
    }

    sentences = _split_sentences(clean_text)
    active_map: dict[str, dict] = {}
    negated_map: dict[str, dict] = {}
    sentence_results = []
    total_deduction = 0.0

    for sent in sentences:
        sent_active_words = []
        sent_negated_words = []
        sent_deduction = 0.0
        # 记录当前句子已匹配的字符区间，防止“失信被执行”与“被执行”重复计分
        occupied_spans: list[tuple[int, int]] = []

        for word, category, base_w in RISK_LEXICON:
            for m in re.finditer(re.escape(word), sent):
                start, end = m.span()
                if any(not (end <= s or start >= e) for s, e in occupied_spans):
                    continue
                occupied_spans.append((start, end))

                # 截取前序 6 字窗口与后序 12 字窗口
                pre_ctx = sent[max(0, start - 6):start]
                post_ctx = sent[end:min(len(sent), end + 12)]

                is_negated = bool(PRE_NEGATION_PATTERNS.search(pre_ctx))
                is_mitigated = bool(POST_MITIGATION_PATTERNS.search(post_ctx))

                if is_negated or is_mitigated:
                    reason = "前序否定排除" if is_negated else "后序结案/缓释"
                    sent_negated_words.append({"word": word, "category": category, "reason": reason})
                    if word not in negated_map:
                        negated_map[word] = {
                            "word": word,
                            "category": category,
                            "count": 0,
                            "status": reason,
                        }
                    negated_map[word]["count"] += 1
                else:
                    eff_w = round(base_w * cat_multiplier.get(category, 1.0), 1)
                    sent_active_words.append({"word": word, "category": category, "weight": eff_w})
                    if word not in active_map:
                        active_map[word] = {
                            "word": word,
                            "category": category,
                            "count": 0,
                            "weight": eff_w,
                            "deduction": 0.0,
                        }
                    active_map[word]["count"] += 1
                    # 同一风险词多次出现采用边际递减扣分
                    step_deduct = eff_w if active_map[word]["count"] == 1 else round(eff_w * 0.45, 1)
                    active_map[word]["deduction"] = round(active_map[word]["deduction"] + step_deduct, 1)
                    sent_deduction += step_deduct

        total_deduction += sent_deduction
        if sent_active_words or sent_negated_words:
            severity = "high" if sent_deduction >= 14 else ("mid" if sent_deduction > 0 else "safe")
            sentence_results.append({
                "sentence": sent,
                "severity": severity,
                "deduction": round(sent_deduction, 1),
                "active_words": sent_active_words,
                "negated_words": sent_negated_words,
            })

    total_score = max(15.0, min(100.0, round(100.0 - total_deduction, 1)))
    level = "低" if total_score >= 80 else ("中" if total_score >= 50 else "高")

    active_list = sorted(active_map.values(), key=lambda x: x["deduction"], reverse=True)
    negated_list = list(negated_map.values())

    return {
        "total_score": total_score,
        "level": level,
        "hits": active_list,
        "negated_hits": negated_list,
        "sentence_analysis": sentence_results,
        "summary": (
            f"共扫描 {len(sentences)} 个分句，检出 {len(active_list)} 类实锤风险词（累计扣减 {round(total_deduction, 1)} 分），"
            f"智能排除/缓释 {len(negated_list)} 类否定语境词。"
        ),
        "elapsed_ms": max(1, int((time.time() - t0) * 1000)),
    }


def check_nlp_health() -> dict:
    nlp_url = os.environ.get("NLP_SERVICE_URL", "http://127.0.0.1:8001").strip()
    try:
        r = requests.get(f"{nlp_url}/health", timeout=2)
        if r.status_code == 200:
            return {"status": "ok", "engine": "NLP 2.0 语义感知引擎 ", "lexicon_size": len(RISK_LEXICON)}
    except Exception:
        pass
    return {"status": "ok", "engine": "NLP 2.0 本地语义感知引擎", "lexicon_size": len(RISK_LEXICON)}
