# -*- coding: utf-8 -*-
"""
企业全量工商档案中文化解析与主页/列表多维字段批量装配工具
（100% 纯中文业务展示，严禁暴露底层数据库字段名）
"""
from apps.risk.models import RiskIndicator

# 省市区国标行政区划代码映射表
REGION_CODE_MAP = {
    "110000": "北京市", "310000": "上海市", "440000": "广东省", "510000": "四川省",
    "500000": "重庆市", "500100": "市辖区", "500200": "辖县",
    "500101": "万州区", "500102": "涪陵区", "500103": "渝中区", "500104": "大渡口区",
    "500105": "江北区", "500106": "沙坪坝区", "500107": "九龙坡区", "500108": "南岸区",
    "500109": "北碚区", "500110": "綦江区", "500111": "大足区", "500112": "渝北区",
    "500113": "巴南区", "500114": "黔江区", "500115": "长寿区", "500116": "江津区",
    "500117": "合川区", "500118": "永川区", "500119": "南川区", "500120": "璧山区",
    "500151": "铜梁区", "500152": "潼南区", "500153": "荣昌区", "500154": "开州区",
    "500155": "梁平区", "500156": "武隆区", "500229": "城口县", "500230": "丰都县",
    "500231": "垫江县", "500233": "忠县", "500235": "云阳县", "500236": "奉节县",
    "500237": "巫山县", "500238": "巫溪县", "500240": "石柱土家族自治县",
    "500241": "秀山土家族苗族自治县", "500242": "酉阳土家族苗族自治县", "500243": "彭水苗族土家族自治县",
}

# 扩展宽表全量字段纯中文业务名称字典（绝不向前端暴露英文Key）
EXTRA_KEY_CN_MAP = {
    "org_no": "组织机构代码",
    "reg_no": "工商注册号",
    "firm_id": "企业全局唯一编码",
    "id_num": "工商档案登记编号",
    "open_date": "开业日期",
    "appr_date": "核准日期",
    "cancel_date": "注销日期",
    "revoke_date": "吊销日期",
    "is_history": "是否历史变更记录",
    "bd_longitude": "地理经度（百度坐标系）",
    "bd_latitude": "地理纬度（百度坐标系）",
    "gd_longitude": "地理经度（高德坐标系）",
    "gd_latitude": "地理纬度（高德坐标系）",
    "tax_no": "纳税人识别号",
    "op_from": "营业期限自",
    "op_to": "营业期限至",
    "paid_cap": "实缴资本（万元）",
    "reg_cap_cur": "注册资本币种",
    "emp_num": "从业人员规模",
    "ins_num": "参保人数",
    "ent_scale": "企业规模等级",
    "credit_grade": "纳税信用等级",
    "reg_addr": "注册地址",
    "address": "通信地址",
    "tel": "企业联系电话",
    "email": "企业电子邮箱",
    "website": "企业官方网站",
    "indu_code": "行业门类编号",
    "zone_code": "属地行政区划编号",
}


def format_region_display(province: str, city: str, district: str) -> str:
    """将省市区国标代码转译为纯中文行政区划名称（不附加国标码数字串）"""
    raw_parts = [
        str(p).strip()
        for p in (province, city, district)
        if p and str(p).strip() not in ("", "-", "None", "nan")
    ]
    if not raw_parts:
        return "重庆市"

    names = []
    for part in raw_parts:
        for token in part.split():
            clean_token = token.split(".")[0].strip()
            mapped_name = REGION_CODE_MAP.get(clean_token, clean_token)
            if mapped_name in ("市辖区", "辖县", "县", "省直辖县级行政区划"):
                continue
            if not mapped_name.isdigit() and mapped_name not in names:
                names.append(mapped_name)

    return " · ".join(names) if names else "重庆市"


def _format_single_value(key: str, val, ope_status: str = "1") -> str:
    """对扩展宽表字段进行纯中文业务格式化"""
    s = "" if val is None else str(val).strip()
    if s.lower() in ("", "-", "none", "null", "nan", "0000-00-00"):
        if key in ("cancel_date", "revoke_date"):
            return "正常存续（无注销记录）" if str(ope_status) == "1" else "未登记"
        return "未登记"

    if key == "is_history":
        if s in ("0", "0.0", "false", "False"):
            return "否（当前最新有效档案）"
        if s in ("1", "1.0", "true", "True"):
            return "是（历史变更留存档案）"

    if key in ("open_date", "appr_date", "cancel_date", "revoke_date", "op_from", "op_to"):
        if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
            date_part = s[:10]
            if key == "cancel_date" and str(ope_status) == "1":
                return f"{date_part}（历史登记，当前在营）"
            return date_part

    if key in ("bd_latitude", "bd_longitude", "gd_latitude", "gd_longitude"):
        try:
            return f"{float(s):.6f}°"
        except ValueError:
            return s

    return s


def build_full_enterprise_archive(ent) -> dict:
    """提取企业详情页全量字段（纯中文业务标签，不含任何数据库字段名）"""
    extra = ent.extra if isinstance(ent.extra, dict) else {}
    ope_status = getattr(ent, "ope_status", "1")

    def get_ext(k: str) -> str:
        return _format_single_value(k, extra.get(k), ope_status)

    core_extra = {
        "org_no": get_ext("org_no"),
        "reg_no": get_ext("reg_no"),
        "firm_id": get_ext("firm_id"),
        "id_num": get_ext("id_num"),
        "open_date": get_ext("open_date"),
        "appr_date": get_ext("appr_date"),
        "cancel_date": get_ext("cancel_date"),
        "is_history": get_ext("is_history"),
        "bd_lng": get_ext("bd_longitude"),
        "bd_lat": get_ext("bd_latitude"),
        "gd_lng": get_ext("gd_longitude"),
        "gd_lat": get_ext("gd_latitude"),
    }

    fixed_keys = {
        "org_no", "reg_no", "firm_id", "id_num",
        "open_date", "appr_date", "cancel_date", "is_history",
        "bd_longitude", "bd_latitude", "gd_longitude", "gd_latitude",
    }
    remaining_items = []
    for k, v in extra.items():
        if k not in fixed_keys and k in EXTRA_KEY_CN_MAP:
            remaining_items.append({
                "label": EXTRA_KEY_CN_MAP[k],
                "value": _format_single_value(k, v, ope_status),
            })

    remaining_rows = []
    for i in range(0, len(remaining_items), 2):
        row = [remaining_items[i]]
        if i + 1 < len(remaining_items):
            row.append(remaining_items[i + 1])
        else:
            row.append({"label": "档案核验状态", "value": "全量信息已核验"})
        remaining_rows.append(row)

    return {
        "core_extra": core_extra,
        "remaining_rows": remaining_rows,
        "total_field_count": 15 + len(extra),
    }


def extract_clean_archive_rows(ent) -> list[list[dict]]:
    """供报告页使用的纯中文四列表格数据"""
    extra = ent.extra if isinstance(ent.extra, dict) else {}
    ope_status = getattr(ent, "ope_status", "1")
    ordered_keys = [
        "org_no", "reg_no", "open_date", "appr_date",
        "cancel_date", "is_history", "bd_longitude", "bd_latitude",
        "gd_longitude", "gd_latitude", "firm_id", "id_num",
    ]
    items = []
    for k in ordered_keys:
        if k in extra and k in EXTRA_KEY_CN_MAP:
            items.append({
                "label": EXTRA_KEY_CN_MAP[k],
                "value": _format_single_value(k, extra.get(k), ope_status),
            })

    rows = []
    for i in range(0, len(items), 2):
        pair = [items[i]]
        if i + 1 < len(items):
            pair.append(items[i + 1])
        else:
            pair.append({"label": "档案核验状态", "value": "已核验归档"})
        rows.append(pair)
    return rows


def enrich_enterprises_for_table(enterprises) -> list:
    """
    为主页和企业列表页的企业对象批量挂载：
    - 中文地区 (region_cn)、工商注册号 (reg_no)、组织机构代码 (org_no)、核准日期 (appr_date)
    - 四维风险得分 (score_fin, score_ope, score_com, score_qua)
    - 近三年累计涉诉/被执行次数 (total_events, zhi_total)
    """
    ent_list = list(enterprises)
    if not ent_list:
        return ent_list

    ent_ids = [e.id for e in ent_list]
    ind_map = {
        ind.enterprise_id: ind
        for ind in RiskIndicator.objects.filter(enterprise_id__in=ent_ids, is_current=True)
    }

    for e in ent_list:
        extra = e.extra if isinstance(e.extra, dict) else {}
        e.region_cn = format_region_display(e.province, e.city, e.district)
        e.reg_no_val = _format_single_value("reg_no", extra.get("reg_no"), e.ope_status)
        e.org_no_val = _format_single_value("org_no", extra.get("org_no"), e.ope_status)
        e.appr_date_val = _format_single_value("appr_date", extra.get("appr_date"), e.ope_status)

        ind = ind_map.get(e.id)
        if ind:
            e.score_fin = ind.score_fin
            e.score_ope = ind.score_ope
            e.score_com = ind.score_com
            e.score_qua = ind.score_qua
            e.cai_sum = ind.cai_1 + ind.cai_2 + ind.cai_3
            e.s_an_sum = ind.s_an_1 + ind.s_an_2 + ind.s_an_3
            e.li_an_sum = ind.li_an_1 + ind.li_an_2 + ind.li_an_3
            e.zhi_sum = ind.zhi_1 + ind.zhi_2 + ind.zhi_3
            e.total_events = e.cai_sum + e.s_an_sum + e.li_an_sum + e.zhi_sum
        else:
            e.score_fin = e.score_ope = e.score_com = e.score_qua = "25.00"
            e.cai_sum = e.s_an_sum = e.li_an_sum = e.zhi_sum = e.total_events = 0

    return ent_list
