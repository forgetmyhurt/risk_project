# -*- coding: utf-8 -*-
"""
企业四维度风险量化评分引擎 v2.0（三层重加权模型）
融合：1. 时间衰减权重 (0.55 / 0.30 / 0.15)
      2. 司法阶段严重度系数 (财务1.00 / 经营0.80 / 合规1.15 / 质量1.40)
      3. 风险趋势动量修正 (爆发加速 ×1.15 / 近1年零新增信用修复 ×0.85)
"""
from decimal import Decimal, ROUND_HALF_UP

# 时间衰减权重：近1年(w1) > 近2年(w2) > 近3年(w3)，总和为 1.0
W_YEAR_1 = 0.55
W_YEAR_2 = 0.30
W_YEAR_3 = 0.15

# 四维度司法严重度系数
SEVERITY_BETA = {
    "fin": 1.00,  # 财务维度：被裁判文书次数（基准）
    "ope": 0.80,  # 经营维度：涉案立案数（含一般纠纷，温和扣分）
    "com": 1.15,  # 合规维度：作为被告被立案（明确被动涉诉，从严扣分）
    "qua": 1.40,  # 质量维度：被强制执行次数（拒不履行/失信高危，重度扣分）
}


def _to_non_neg_int(val) -> int:
    try:
        return max(0, int(float(val or 0)))
    except (ValueError, TypeError):
        return 0


def _q2(val: float) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# 打开 services/risk_calc.py，将 _calc_dimension_weighted_deduction 函数替换为：
def _calc_dimension_weighted_deduction(x1: int, x2: int, x3: int, dim_key: str) -> tuple[Decimal, Decimal]:
    """
    计算单个维度的重加权扣分值与最终得分（含非线性边际递减阻尼，消除分布断层）
    """
    time_weighted_base = W_YEAR_1 * x1 + W_YEAR_2 * x2 + W_YEAR_3 * x3
    beta = SEVERITY_BETA.get(dim_key, 1.0)

    if x1 > x2 and x1 > x3 and x1 >= 2:
        gamma = 1.12
    elif x1 == 0 and (x2 > 0 or x3 > 0):
        gamma = 0.88
    else:
        gamma = 1.00

    raw_deduction = time_weighted_base * beta * gamma
    # 引入 0.90 次幂边际递减阻尼：高次涉诉平滑过渡，避免分数扎堆断层
    smooth_deduction = (raw_deduction ** 0.90) * 1.15 if raw_deduction > 0 else 0.0
    score = max(0.0, 25.0 - smooth_deduction)
    return _q2(smooth_deduction), _q2(score)

def calc_risk_score(metrics: dict, low_th: float = 80.0, mid_th: float = 50.0) -> dict:
    """
    输入 12 项原始指标字典，输出重加权后的四维扣分、四维得分、总分与风险等级
    """
    cai_1, cai_2, cai_3 = _to_non_neg_int(metrics.get("cai_1")), _to_non_neg_int(metrics.get("cai_2")), _to_non_neg_int(metrics.get("cai_3"))
    s_an_1, s_an_2, s_an_3 = _to_non_neg_int(metrics.get("s_an_1")), _to_non_neg_int(metrics.get("s_an_2")), _to_non_neg_int(metrics.get("s_an_3"))
    li_an_1, li_an_2, li_an_3 = _to_non_neg_int(metrics.get("li_an_1")), _to_non_neg_int(metrics.get("li_an_2")), _to_non_neg_int(metrics.get("li_an_3"))
    zhi_1, zhi_2, zhi_3 = _to_non_neg_int(metrics.get("zhi_1")), _to_non_neg_int(metrics.get("zhi_2")), _to_non_neg_int(metrics.get("zhi_3"))

    num_fin, score_fin = _calc_dimension_weighted_deduction(cai_1, cai_2, cai_3, "fin")
    num_ope, score_ope = _calc_dimension_weighted_deduction(s_an_1, s_an_2, s_an_3, "ope")
    num_com, score_com = _calc_dimension_weighted_deduction(li_an_1, li_an_2, li_an_3, "com")
    num_qua, score_qua = _calc_dimension_weighted_deduction(zhi_1, zhi_2, zhi_3, "qua")

    total_score = score_fin + score_ope + score_com + score_qua
    total_float = float(total_score)

    if total_float >= low_th:
        level = "L"
    elif total_float >= mid_th:
        level = "M"
    else:
        level = "H"

    return {
        "cai_1": cai_1, "cai_2": cai_2, "cai_3": cai_3,
        "s_an_1": s_an_1, "s_an_2": s_an_2, "s_an_3": s_an_3,
        "li_an_1": li_an_1, "li_an_2": li_an_2, "li_an_3": li_an_3,
        "zhi_1": zhi_1, "zhi_2": zhi_2, "zhi_3": zhi_3,
        "num_fin": num_fin, "score_fin": score_fin,
        "num_ope": num_ope, "score_ope": score_ope,
        "num_com": num_com, "score_com": score_com,
        "num_qua": num_qua, "score_qua": score_qua,
        "total_risk_score": total_score,
        "risk_level": level,
    }
