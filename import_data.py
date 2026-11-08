# -*- coding: utf-8 -*-
"""万级 CSV 数据清洗与批量入库脚本：用法 python import_data.py"""
import os
from datetime import datetime
from decimal import Decimal
import django
import pandas as pd

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "risk_project_liutianyu.settings")
django.setup()

from django.db import transaction
from apps.enterprise.models import Enterprise
from apps.risk.models import RiskIndicator
from dataset_process import DATA_DIR, is_missing, to_num, to_date
from services.risk_calc import calc_risk_score

CORE_REG_COLS = {
    "id", "firm_eid", "firm_name", "usc_code", "legal_rep", "firm_category",
    "firm_type", "ope_status", "est_date", "reg_cap", "ind_econ_name",
    "province", "city", "district", "reg_agency", "ope_scope", "business_scope"
}

def clean_str(val, max_len=None):
    if val is None or str(val).strip().lower() in {"", "null", "none", "nan", "na", "n/a", "-", "--", "/", "无", "未知"}:
        return ""
    s = str(val).strip()
    return s[:max_len] if max_len else s

def main():
    reg_df = pd.read_csv(DATA_DIR / "dwd_essential_info_commercial_reg_info_1w.csv", dtype=str, keep_default_na=False)
    risk_df = pd.read_csv(DATA_DIR / "ads_company_rating_basis_1w.csv", dtype=str, keep_default_na=False)
    reg_df.columns = [c.strip() for c in reg_df.columns]
    risk_df.columns = [c.strip() for c in risk_df.columns]

    # cleaning numerical & date series using dataset_process utilities
    reg_cap_s = to_num(reg_df["reg_cap"].where(~is_missing(reg_df["reg_cap"]))).fillna(0)
    est_date_s = to_date(reg_df["est_date"].where(~is_missing(reg_df["est_date"])))
    risk_map = risk_df.set_index("id").to_dict("index")

    now = datetime.now()
    batch_no = "20261103-01"
    enterprises = []
    seen_eid, seen_usc = set(), set()

    print("正在清洗并计算 10,000 家企业与风险评分...")
    for idx, row in reg_df.iterrows():
        rid = clean_str(row.get("id"))
        r_row = risk_map.get(rid, {})
        score_res = calc_risk_score(r_row)

        eid = clean_str(row.get("firm_eid") or rid, 64) or None
        if eid and eid in seen_eid:
            eid = None
        if eid:
            seen_eid.add(eid)

        usc = clean_str(row.get("usc_code"), 18) or None
        if usc and usc in seen_usc:
            usc = None
        if usc:
            seen_usc.add(usc)

        cat = clean_str(row.get("firm_category"), 1)
        cat = cat if cat in ("E", "P") else "E"
        status = clean_str(row.get("ope_status"), 2)
        status = status if status in ("1", "2", "3") else "1"

        dt = est_date_s.iloc[idx]
        est_date_val = dt.date() if pd.notna(dt) else None
        cap_val = Decimal(f"{max(0.0, float(reg_cap_s.iloc[idx])):.2f}")

        # 其余宽表字段存入 extra JSON
        extra_data = {
            k: clean_str(row[k]) for k in reg_df.columns
            if k not in CORE_REG_COLS and clean_str(row[k]) not in ("", "-1")
        }

        ent = Enterprise(
            firm_eid=eid,
            firm_name=clean_str(row.get("firm_name") or r_row.get("name") or f"未知企业_{idx}", 200),
            usc_code=usc,
            legal_rep=clean_str(row.get("legal_rep") or r_row.get("f_ren"), 50),
            firm_category=cat,
            firm_type=clean_str( r_row.get("qiye_type") or row.get("firm_type"), 100),
            ope_status=status,
            est_date=est_date_val,
            reg_cap=cap_val,
            ind_econ_name=clean_str(row.get("ind_econ_name"), 100),
            province=clean_str(row.get("province"), 50),
            city=clean_str(row.get("city"), 50),
            district=clean_str(row.get("district"), 50),
            reg_agency=clean_str(row.get("reg_agency"), 100),
            business_scope=clean_str(row.get("business_scope") or row.get("ope_scope") or r_row.get("jing_fan")),
            risk_level=score_res["risk_level"],
            score_total=score_res["total_risk_score"],
            last_scored_at=now,
            extra=extra_data,
        )
        ent._score_cache = score_res
        enterprises.append(ent)

    with transaction.atomic():
        RiskIndicator.objects.all().delete()
        Enterprise.objects.all().delete()
        Enterprise.objects.bulk_create(enterprises, batch_size=1000)

        db_ents = list(Enterprise.objects.all().order_by("id"))
        indicators = []
        for ent, orig in zip(db_ents, enterprises):
            sc = orig._score_cache
            indicators.append(
                RiskIndicator(
                    enterprise=ent,
                    batch_no=batch_no,
                    cai_1=sc["cai_1"], cai_2=sc["cai_2"], cai_3=sc["cai_3"],
                    s_an_1=sc["s_an_1"], s_an_2=sc["s_an_2"], s_an_3=sc["s_an_3"],
                    li_an_1=sc["li_an_1"], li_an_2=sc["li_an_2"], li_an_3=sc["li_an_3"],
                    zhi_1=sc["zhi_1"], zhi_2=sc["zhi_2"], zhi_3=sc["zhi_3"],
                    score_fin=sc["score_fin"], score_ope=sc["score_ope"],
                    score_com=sc["score_com"], score_qua=sc["score_qua"],
                    total_risk_score=sc["total_risk_score"],
                    risk_level=sc["risk_level"],
                    algo_version=sc["algo_version"],
                    name=ent.firm_name,
                    usc_code=ent.usc_code or "",
                    ope_status=ent.ope_status,
                    scored_at=now,
                    is_current=True,
                )
            )
        RiskIndicator.objects.bulk_create(indicators, batch_size=1000)

    print(f"入库完成：Enterprise 共 {Enterprise.objects.count()} 条，RiskIndicator 共 {RiskIndicator.objects.count()} 条。")

if __name__ == "__main__":
    main()
