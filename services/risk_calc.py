from decimal import Decimal, ROUND_HALF_UP

DIM_FIELDS = {
    "score_fin": ("cai_1", "cai_2", "cai_3"),
    "score_ope": ("s_an_1", "s_an_2", "s_an_3"),
    "score_com": ("li_an_1", "li_an_2", "li_an_3"),
    "score_qua": ("zhi_1", "zhi_2", "zhi_3"),
}

def _to_pos_int(val) -> int:
    try:
        v = int(float(val))
        return max(0, v)
    except (ValueError, TypeError):
        return 0

def calc_risk_score(metrics: dict, low_th: float = 80.0, mid_th: float = 50.0) -> dict:
    """
    四维度扣分制计算（FR-03-01）：
    n_d = round((x1 + x2 + x3) / 3, 2)
    S_d = max(0, 25 - n_d)
    S = S_财 + S_经 + S_合 + S_质（保留1位小数）
    """
    cleaned = {}
    scores = {}
    for dim_key, cols in DIM_FIELDS.items():
        vals = [_to_pos_int(metrics.get(c, 0)) for c in cols]
        for c, v in zip(cols, vals):
            cleaned[c] = v
        n_d = round(sum(vals) / 3.0, 2)
        s_d = max(0.0, round(25.0 - n_d, 2))
        scores[dim_key] = Decimal(str(s_d)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total = float(sum(scores.values()))
    total_rounded = round(total, 1)
    if total_rounded >= low_th:
        level = "L"
    elif total_rounded >= mid_th:
        level = "M"
    else:
        level = "H"

    return {
        **cleaned,
        **scores,
        "total_risk_score": Decimal(str(total_rounded)).quantize(Decimal("0.01")),
        "risk_level": level,
        "algo_version": "v1.0",
    }
