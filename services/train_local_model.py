# -*- coding: utf-8 -*-
"""
本地风险评估模型自训练与指令微调数据集生成脚本
用法：python train_local_model.py

产出：
1. services/local_risk_model.pkl
   （本地自训练：风控意图分类器 + 12项指标特征归因随机森林模型）

2. dataset/risk_sft_train.jsonl
   （供 Qwen2.5-1.5B LoRA 微调的标准问答数据集）
"""

import json
from pathlib import Path
import os

import django
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

# ===================== Django 初始化 =====================
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "risk_project_liutianyu.settings")
django.setup()

from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator

# ===================== 路径配置（已修复） =====================
BASE_DIR = Path(__file__).resolve().parent                 # services/
PROJECT_DIR = BASE_DIR.parent                              # 项目根目录

MODEL_PATH = BASE_DIR / "local_risk_model.pkl"             # services/local_risk_model.pkl
SFT_JSONL_PATH = PROJECT_DIR / "dataset" / "risk_sft_train.jsonl"

# ===================== 特征配置 =====================
FEATURE_COLS = [
    "cai_1", "cai_2", "cai_3",
    "s_an_1", "s_an_2", "s_an_3",
    "li_an_1", "li_an_2", "li_an_3",
    "zhi_1", "zhi_2", "zhi_3",
]

FEATURE_NAMES_CN = [
    "近1年被裁判", "近2年被裁判", "近3年被裁判",
    "近1年涉案立案", "近2年涉案立案", "近3年涉案立案",
    "近1年被立案", "近2年被立案", "近3年被立案",
    "近1年被执行", "近2年被执行", "近3年被执行",
]

# ===================== 风控意图语料 =====================
INTENT_CORPUS = [
    # weakness
    ("分析该企业的四维度薄弱项与扣分原因", "weakness"),
    ("为什么这家公司得分这么低？哪里扣分最多", "weakness"),
    ("剖析四维度短板和主要风险点", "weakness"),
    ("财务经营合规质量四个维度哪个最差", "weakness"),
    ("查看企业扣分明细与核心弱项", "weakness"),
    ("这家企业存在哪些主要风险隐患", "weakness"),

    # credit
    ("生成该企业的信贷准入与风控缓释建议", "credit"),
    ("这家公司可以放款吗？授信额度怎么给", "credit"),
    ("银行信贷审批准入结论与担保要求", "credit"),
    ("给出供应链金融合作与风险防控建议", "credit"),
    ("如果给该企业贷款需要注意什么风控措施", "credit"),
    ("请对企业进行全面风险评估并给出信贷准入建议", "credit"),

    # judicial
    ("综合评估该企业近三年涉诉与被执行风险", "judicial"),
    ("解读司法执行风险和裁判文书情况", "judicial"),
    ("有没有被法院强制执行或立案调查记录", "judicial"),
    ("近三年官司诉讼多不多，败诉执行情况如何", "judicial"),
    ("分析合规与质量维度的立案及被执行次数", "judicial"),

    # contagion
    ("请结合风险图谱分析关联方与法定代表人风险传染路径", "contagion"),
    ("法人名下其他关联公司有没有高风险传染", "contagion"),
    ("穿透排查股东、法定代表人及同业关联风险", "contagion"),
    ("关联企业图谱中是否存在失信传染源", "contagion"),

    # sandbox
    ("我在沙箱模拟器中进行了What-If演练，请评估该缓释方案的可行性与授信条件", "sandbox"),
    ("模拟结清被执行后得分提升，这个修复方案可行吗", "sandbox"),
    ("沙箱推演预测等级变化后的准入评估", "sandbox"),
    ("如果减少司法诉讼次数，风险等级能否下调", "sandbox"),

    # general
    ("你们系统的评分规则和等级阈值是怎么算的", "general"),
    ("介绍一下这家企业的基本画像与当前评级", "general"),
    ("综合评估这家公司目前的风险状况", "general"),
    ("满分100扣分制公式是什么", "general"),
]


# ===================== 模型训练 =====================
def train_intent_classifier():
    """字符级 N-Gram TF-IDF + 逻辑回归意图识别器"""
    texts = [t for t, _ in INTENT_CORPUS]
    labels = [y for _, y in INTENT_CORPUS]

    clf = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3))),
        ("lr", LogisticRegression(C=5.0, max_iter=500)),
    ])
    clf.fit(texts, labels)
    return clf


def train_risk_attribution_model():
    """基于 RiskIndicator 数据训练随机森林"""
    qs = RiskIndicator.objects.filter(is_current=True).values(*FEATURE_COLS, "risk_level")

    if not qs.exists():
        raise RuntimeError("数据库中尚无 RiskIndicator 数据，请先运行 import_data.py")

    X, y = [], []
    level_to_idx = {"L": 0, "M": 1, "H": 2}

    for row in qs:
        X.append([int(row[c] or 0) for c in FEATURE_COLS])
        y.append(level_to_idx.get(row["risk_level"], 0))

    X_arr = np.array(X, dtype=np.float32)
    y_arr = np.array(y, dtype=np.int32)

    rf = RandomForestClassifier(
        n_estimators=80,
        max_depth=8,
        random_state=42,
        class_weight="balanced"
    )
    rf.fit(X_arr, y_arr)

    acc = rf.score(X_arr, y_arr)
    print(f"[本地模型训练] 样本数: {len(X_arr)} 条 | 分类准确率: {acc * 100:.2f}%")
    return rf


# ===================== SFT 数据集生成 =====================
def export_sft_dataset(limit: int = 500):
    inds = (
        RiskIndicator.objects
        .select_related("enterprise")
        .filter(is_current=True)
        .order_by("total_risk_score")[:limit]
    )

    records = []
    lvl_cn = {"L": "低风险", "M": "中风险", "H": "高风险"}

    for ind in inds:
        ent = ind.enterprise
        ctx_str = (
            f"企业名称：{ent.firm_name}；行业：{ent.ind_econ_name or '综合'}；"
            f"经营状态：{ent.get_ope_status_display()}；注册资本：{ent.reg_cap}万元；"
            f"综合得分：{ind.total_risk_score}分（{lvl_cn.get(ind.risk_level, '低风险')}）；"
            f"四维得分：财务{ind.score_fin}/经营{ind.score_ope}/合规{ind.score_com}/质量{ind.score_qua}；"
            f"近1/2/3年指标：被裁判{ind.cai_1}/{ind.cai_2}/{ind.cai_3}，"
            f"立案{ind.s_an_1}/{ind.s_an_2}/{ind.s_an_3}，"
            f"被立案{ind.li_an_1}/{ind.li_an_2}/{ind.li_an_3}，"
            f"被执行{ind.zhi_1}/{ind.zhi_2}/{ind.zhi_3}。"
        )

        if ind.risk_level == "L":
            advice = "建议按常规授信标准准入。"
        elif ind.risk_level == "M":
            advice = "存在一定历史涉诉记录，建议收紧授信敞口并追加担保。"
        else:
            advice = "司法执行与涉诉风险突出，建议审慎准入或拒贷。"

        ans = (
            f"【{ent.firm_name}】综合风险得分为 {ind.total_risk_score} 分，"
            f"评级为{lvl_cn.get(ind.risk_level, '低风险')}。"
            f"四维度中财务得 {ind.score_fin} 分、经营得 {ind.score_ope} 分、"
            f"合规得 {ind.score_com} 分、质量得 {ind.score_qua} 分。"
            f"{advice}"
        )

        records.append({
            "instruction": "你是企业信贷风控专家，请根据给定的企业工商与12项风险指标快照，"
                           "输出风险诊断结论与授信准入建议。",
            "input": ctx_str,
            "output": ans,
        })

    SFT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SFT_JSONL_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[SFT数据集导出] 已生成 {len(records)} 条微调语料 -> {SFT_JSONL_PATH}")


# ===================== 主流程 =====================
def main():
    intent_clf = train_intent_classifier()
    rf_model = train_risk_attribution_model()

    bundle = {
        "version": "v2.0-local-ml",
        "intent_clf": intent_clf,
        "rf_model": rf_model,
        "feature_cols": FEATURE_COLS,
        "feature_names_cn": FEATURE_NAMES_CN,
    }

    joblib.dump(bundle, MODEL_PATH)
    print(f"[模型保存成功] 权重已写入 -> {MODEL_PATH}")

    export_sft_dataset()


if __name__ == "__main__":
    main()