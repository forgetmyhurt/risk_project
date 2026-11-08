# -*- coding: utf-8 -*-
"""
企业工商宽表字段清洗与国标行政区划代码转译工具
"""

# 重庆市及常见省市区国标行政区划代码映射表
REGION_CODE_MAP = {
    "110000": "北京市", "310000": "上海市", "440000": "广东省", "510000": "四川省",
    "500000": "重庆市", "500100": "市辖区", "500200": "县",
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

# 明确剔除的底层无意义主键、坐标与状态标志
IGNORED_EXTRA_KEYS = {
    "id_num", "firm_id", "firm_eid", "is_history",
    "bd_latitude", "bd_longitude", "gd_latitude", "gd_longitude",
    "lat", "lng", "latitude", "longitude",
    "province", "city", "district",
}

# 扩展宽表有价值业务字段白名单与标准中文名称映射（按尽调重要度排序）
EXTRA_FIELD_WHITELIST = [
    ("org_no", "组织机构代码"),
    ("reg_no", "工商注册号"),
    ("tax_no", "纳税人识别号"),
    ("open_date", "开业日期"),
    ("appr_date", "核准日期"),
    ("cancel_date", "注销日期"),
    ("revoke_date", "吊销日期"),
    ("op_from", "营业期限自"),
    ("op_to", "营业期限至"),
    ("paid_cap", "实缴资本(万元)"),
    ("reg_cap_cur", "注册资本币种"),
    ("emp_num", "参保/从业人数"),
    ("ins_num", "参保人数"),
    ("ent_Scale", "企业规模"),
    ("credit_grade", "纳税信用等级"),
    ("reg_addr", "注册地址"),
    ("address", "通信地址"),
    ("tel", "企业联系电话"),
    ("email", "企业电子邮箱"),
    ("website", "企业网址"),
]


def format_region_display(province: str, city: str, district: str) -> str:
    """将省市区代码或原始字符串转译为标准中文行政区划"""
    raw_parts = [str(p).strip() for p in (province, city, district) if p and str(p).strip() not in ("", "-", "None", "nan")]
    if not raw_parts:
        return "-"

    translated = []
    for part in raw_parts:
        for token in part.split():
            clean_token = token.split(".")[0].strip()
            name = REGION_CODE_MAP.get(clean_token, clean_token)
            # 过滤“市辖区”、“县”等冗余中间层级及重复地名
            if name in ("市辖区", "县", "省直辖县级行政区划"):
                continue
            if name not in translated:
                translated.append(name)

    return " ".join(translated) if translated else "-"


def _clean_val(val) -> str:
    """格式化单个字段值，截取冗余时间戳"""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("", "-", "none", "null", "nan", "0000-00-00"):
        return ""
    if len(s) >= 19 and s[4:5] == "-" and s[7:8] == "-" and " " in s:
        return s[:10]
    return s


def extract_clean_archive_rows(ent) -> list[list[dict]]:
    """
    提取并清洗企业扩展宽表字段，按每行 2 组键值对（4列对称表格）组装返回
    返回结构：[[{"label": "组织机构代码", "value": "054286454"}, {"label": "工商注册号", "value": "..."}], ...]
    """
    extra = ent.extra or {}
    if not isinstance(extra, dict):
        return []

    items = []
    used_keys = set()

    # 1. 按白名单顺序提取高价值工商字段
    for key, label in EXTRA_FIELD_WHITELIST:
        if key in extra and key not in IGNORED_EXTRA_KEYS:
            val = _clean_val(extra[key])
            if val:
                items.append({"label": label, "value": val})
                used_keys.add(key)

    # 2. 两两配对组装为四列表格行（不足偶数时自动补齐空单元格）
    rows = []
    for i in range(0, len(items), 2):
        pair = [items[i]]
        if i + 1 < len(items):
            pair.append(items[i + 1])
        else:
            pair.append({"label": "档案状态", "value": "已核验归档"})
        rows.append(pair)

    return rows
