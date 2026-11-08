import re
from apps.enterprise.models import Enterprise

LEVEL_COLOR = {"L": "#1E7B45", "M": "#B7791F", "H": "#C0392B"}
LEVEL_NAME = {"L": "低风险", "M": "中风险", "H": "高风险"}

# 常见复姓表与女性名字特征字库（用于无显式性别标注时的智能称谓推断）
COMPOUND_SURNAMES = {
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟", "闻人",
    "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政", "濮阳", "公冶",
    "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于",
    "司空", "闾丘", "子车", "亓官", "司寇", "巫马", "公西", "颛孙", "壤驷", "公良",
    "漆雕", "乐正", "宰父", "谷梁", "拓跋", "夹谷", "轩辕", "令狐", "段干", "百里",
    "呼延", "东郭", "南门", "羊舌", "微生", "西门", "第五",
}
FEMALE_NAME_CHARS = set(
    "敏婷娟芳娜秀英华慧巧美静淑惠珠翠雅芝玉萍红娥玲芬燕彩春菊兰凤洁梅琳素云莲真环雪荣爱妹霞香月莺媛艳"
    "瑞佳嘉琼珍贞莉桂娣叶璧璐娅琦晶妍茜秋珊莎锦黛青倩姣婉娴瑾颖露瑶怡婵雁蓓纨仪荷丹蓉眉琴蕊薇菁梦岚苑"
    "婕馨瑗琰韵园艺咏卿澜纯毓悦冰琬茗羽欣飘滢馥筠柔竹凝晓欢芸菲伊亚宜可姬舒影思丽倩妮媛姿妙妤娆娇娉"
)


def mask_legal_rep_name(raw_name: str, extra: "dict | None" = None) -> str:
    """
    法定代表人姓名脱敏处理：
    例如：'刘敏（女）' -> '刘女士'，'杨梁（男）' -> '杨先生'，'欧阳娜（女）' -> '欧阳女士'
    """
    if not raw_name or str(raw_name).strip() in ("", "-", "无", "未知"):
        return "未知法人"

    text = str(raw_name).strip()
    extra = extra or {}

    # 1. 优先从原始字符串中识别显式性别标记：如（女）、(男)、女士、先生
    gender = None
    if re.search(r"[（(\-\s/]女[）)\s]*|女士|小姐", text):
        gender = "F"
    elif re.search(r"[（(\-\s/]男[）)\s]*|先生", text):
        gender = "M"

    # 2. 若字符串无显式标记，尝试从扩展字段 extra（性别字段或18位身份证第17位奇偶）识别
    if not gender:
        sex_val = str(extra.get("gender") or extra.get("sex") or extra.get("legal_rep_sex") or "")
        if "女" in sex_val or sex_val.upper() == "F":
            gender = "F"
        elif "男" in sex_val or sex_val.upper() == "M":
            gender = "M"
        else:
            id_no = str(extra.get("legal_rep_id_no") or extra.get("legal_rep_id") or "")
            if len(id_no) == 18 and id_no[16].isdigit():
                gender = "M" if int(id_no[16]) % 2 == 1 else "F"

    # 3. 剥离括号备注、特殊符号与已有的先生/女士后缀，提取纯姓名
    clean_name = re.sub(r"（.*?）|\(.*?\)|\[.*?\]", "", text)
    clean_name = re.sub(r"(先生|女士|小姐|同志|法人|[-\s/男女性别：:])", "", clean_name).strip()
    if not clean_name:
        return "某先生/女士"

    # 4. 提取姓氏（兼容复姓）與名字
    if len(clean_name) >= 3 and clean_name[:2] in COMPOUND_SURNAMES:
        surname = clean_name[:2]
        given_name = clean_name[2:]
    else:
        surname = clean_name[0]
        given_name = clean_name[1:]

    # 5. 若仍未确定性别，基于名字特征字智能判定（含女性高频字则为女士，否则默认先生）
    if not gender:
        if any(ch in FEMALE_NAME_CHARS for ch in given_name):
            gender = "F"
        else:
            gender = "M"

    title = "女士" if gender == "F" else "先生"
    return f"{surname}{title}"


def build_enterprise_risk_graph(ent: Enterprise) -> dict:
    """
    构建企业风险图谱与关联方穿透数据（迭代点6）：
    节点类别：0-当前核心企业, 1-法定代表人/监管, 2-法人共管关联企业, 3-同业/区域风险传染节点
    """
    nodes = []
    links = []
    seen_ent_ids = {ent.id}
    high_risk_sources = []

    # 1. 中心节点：当前企业
    center_id = f"ent_{ent.id}"
    nodes.append({
        "id": center_id,
        "ent_id": ent.id,
        "name": ent.firm_name,
        "symbolSize": 54,
        "category": 0,
        "risk_level": ent.risk_level,
        "score": float(ent.score_total),
        "role_desc": f"核心评估主体（{LEVEL_NAME.get(ent.risk_level, '低风险')} · {ent.score_total}分）",
        "itemStyle": {"color": LEVEL_COLOR.get(ent.risk_level, "#1E7B45"), "borderColor": "#fff", "borderWidth": 3},
    })

    # 2. 法定代表人节点（姓名脱敏展示，底层仍按真实姓名精准匹配共管企业）
    rep_raw = (ent.legal_rep or "").strip()
    if rep_raw and rep_raw != "-":
        masked_rep = mask_legal_rep_name(rep_raw, ent.extra)
        rep_node_id = f"rep_{ent.id}"
        nodes.append({
            "id": rep_node_id,
            "name": f"法人：{masked_rep}",
            "symbolSize": 40,
            "category": 1,
            "risk_level": ent.risk_level,
            "score": float(ent.score_total),
            "role_desc": f"法定代表人：{masked_rep}（已按隐私规范脱敏）",
            "itemStyle": {"color": "#2563eb", "borderColor": "#dbeafe", "borderWidth": 2},
        })
        links.append({
            "source": rep_node_id,
            "target": center_id,
            "relation": "法定代表人",
            "lineStyle": {"width": 2.5, "color": "#2563eb"},
        })

        # 查询同一法定代表人名下的其他关联企业（数据库底层使用原字段匹配）
        co_ents = Enterprise.objects.filter(legal_rep=rep_raw).exclude(pk=ent.id).order_by("score_total")[:6]
        for ce in co_ents:
            seen_ent_ids.add(ce.id)
            nid = f"ent_{ce.id}"
            if ce.risk_level in ("H", "M"):
                high_risk_sources.append(f"{masked_rep}共管关联企【{ce.firm_name}】（{LEVEL_NAME[ce.risk_level]} {ce.score_total}分）")
            nodes.append({
                "id": nid,
                "ent_id": ce.id,
                "name": ce.firm_name,
                "symbolSize": 36,
                "category": 2,
                "risk_level": ce.risk_level,
                "score": float(ce.score_total),
                "role_desc": f"{masked_rep}名下关联企业（{LEVEL_NAME.get(ce.risk_level, '低风险')} · {ce.score_total}分）",
                "itemStyle": {"color": LEVEL_COLOR.get(ce.risk_level, "#1E7B45")},
            })
            links.append({
                "source": rep_node_id,
                "target": nid,
                "relation": "名下共管企业",
                "lineStyle": {"type": "solid", "width": 2, "color": LEVEL_COLOR.get(ce.risk_level, "#94a3b8")},
            })

    # 3. 属地登记机关监管节点
    extra = ent.extra or {}
    reg_agency_name = ent.reg_agency or extra.get("reg_agency_name", "")
    if reg_agency_name:
        ag_node_id = f"ag_{ent.id}"
        nodes.append({
            "id": ag_node_id,
            "name": reg_agency_name[:12],
            "symbolSize": 30,
            "category": 1,
            "risk_level": "L",
            "score": 100.0,
            "role_desc": f"主管登记机关：{reg_agency_name}",
            "itemStyle": {"color": "#64748b"},
        })
        links.append({
            "source": ag_node_id,
            "target": center_id,
            "relation": "属地监管",
            "lineStyle": {"type": "dotted", "color": "#94a3b8"},
        })

    # 4. 同行业/同区域上下游与风险传染监测节点
    peer_q = Enterprise.objects.exclude(pk__in=seen_ent_ids)
    if ent.ind_econ_name:
        peer_q = peer_q.filter(ind_econ_name=ent.ind_econ_name)
    elif ent.firm_type:
        peer_q = peer_q.filter(firm_type=ent.firm_type)
    elif ent.district:
        peer_q = peer_q.filter(district=ent.district)

    peers = list(peer_q.order_by("score_total", "id")[:6])
    if len(peers) < 4:
        more = Enterprise.objects.exclude(pk__in=seen_ent_ids).order_by("score_total")[: (6 - len(peers))]
        peers.extend(more)

    for pe in peers[:6]:
        if pe.id in seen_ent_ids:
            continue
        seen_ent_ids.add(pe.id)
        nid = f"ent_{pe.id}"
        if pe.risk_level == "H":
            high_risk_sources.append(f"同业高危传染源【{pe.firm_name}】（{pe.score_total}分）")
        nodes.append({
            "id": nid,
            "ent_id": pe.id,
            "name": pe.firm_name,
            "symbolSize": 32,
            "category": 3,
            "risk_level": pe.risk_level,
            "score": float(pe.score_total),
            "role_desc": f"同业/区域关联监测（{LEVEL_NAME.get(pe.risk_level, '低风险')} · {pe.score_total}分）",
            "itemStyle": {"color": LEVEL_COLOR.get(pe.risk_level, "#1E7B45")},
        })
        links.append({
            "source": center_id,
            "target": nid,
            "relation": "同业/区域关联",
            "lineStyle": {
                "type": "dashed",
                "width": 1.8 if pe.risk_level == "H" else 1.2,
                "color": LEVEL_COLOR.get(pe.risk_level, "#cbd5e1"),
            },
        })

    return {
        "nodes": nodes,
        "links": links,
        "high_risk_count": sum(1 for n in nodes if n.get("risk_level") == "H" and n["id"] != center_id),
        "contagion_alerts": high_risk_sources[:3],
    }
