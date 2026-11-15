# -*- coding: utf-8 -*-
import io
import re
from pathlib import Path
from urllib.parse import quote
from fpdf import FPDF
from services.archive_cleaner import extract_clean_archive_rows, format_region_display

LEVEL_MAP = {"L": "低风险", "M": "中风险", "H": "高风险"}


def _clean_pdf_text(val) -> str:
    """清理文本中的 Markdown 星号、换行符与空白占位"""
    if val is None:
        return "-"
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "nan"):
        return "-"
    s = re.sub(r"\*+", "", s)
    s = re.sub(r"[\r\n]+", " ", s)
    return s


def _dim_desc(name: str, score: float) -> str:
    """按维度得分区间生成说明文字（FR-03-02）"""
    if score >= 22:
        return f"{name}维度得分 {score:.2f}/25.00，近三年相关涉诉与执行记录极少，表现良好。"
    if score >= 15:
        return f"{name}维度得分 {score:.2f}/25.00，存在一定频次的司法或经营风险记录，建议持续关注。"
    return f"{name}维度得分 {score:.2f}/25.00，相关风险事件频发，扣分较多，建议重点核查。"


def build_report_context(indicator) -> dict:
    """组装报告上下文数据（含四维重加权扣分计算与清洗后的工商宽表行）"""
    ent = indicator.enterprise
    s_fin = float(indicator.score_fin)
    s_ope = float(indicator.score_ope)
    s_com = float(indicator.score_com)
    s_qua = float(indicator.score_qua)
    total = float(indicator.total_risk_score)
    lvl_cn = LEVEL_MAP.get(indicator.risk_level, "低风险")

    # 动态计算并挂载各维度扣分值（满分 25 减去当前维度得分），供网页与 PDF 表格共同使用
    d_fin = f"{max(0.0, 25.0 - s_fin):.2f}"
    d_ope = f"{max(0.0, 25.0 - s_ope):.2f}"
    d_com = f"{max(0.0, 25.0 - s_com):.2f}"
    d_qua = f"{max(0.0, 25.0 - s_qua):.2f}"

    indicator.num_fin = d_fin
    indicator.num_ope = d_ope
    indicator.num_com = d_com
    indicator.num_qua = d_qua

    if indicator.risk_level == "L":
        conclusion = (
            f"该企业综合风险得分为 {total:.2f} 分，评级为【{lvl_cn}】。"
            "四维司法与经营指标整体稳健，近一年无重大集中涉诉或强制执行爆发，建议适用标准授信准入通道。"
        )
    elif indicator.risk_level == "M":
        conclusion = (
            f"该企业综合风险得分为 {total:.2f} 分，评级为【{lvl_cn}】。"
            "部分维度存在一定频次的历史涉诉或立案记录，建议审慎核查未结案件，压缩授信敞口至常规额度的 60%~70%，并追加连带责任担保。"
        )
    else:
        conclusion = (
            f"该企业综合风险得分为 {total:.2f} 分，评级为【{lvl_cn}】。"
            "司法诉讼或被强制执行风险敞口突出，建议触发风控拦截，或要求提供法院结案证明及足额抵押物后再行复议。"
        )

    dimensions = [
        {"name": "财务维度", "metric": "被裁判文书次数", "y1": indicator.cai_1, "y2": indicator.cai_2, "y3": indicator.cai_3, "deduct": f"-{d_fin}", "score": f"{s_fin:.2f}", "desc": _dim_desc("财务", s_fin)},
        {"name": "经营维度", "metric": "涉案立案次数", "y1": indicator.s_an_1, "y2": indicator.s_an_2, "y3": indicator.s_an_3, "deduct": f"-{d_ope}", "score": f"{s_ope:.2f}", "desc": _dim_desc("经营", s_ope)},
        {"name": "合规维度", "metric": "作为被告被立案次数", "y1": indicator.li_an_1, "y2": indicator.li_an_2, "y3": indicator.li_an_3, "deduct": f"-{d_com}", "score": f"{s_com:.2f}", "desc": _dim_desc("合规", s_com)},
        {"name": "质量维度", "metric": "被法院强制执行次数", "y1": indicator.zhi_1, "y2": indicator.zhi_2, "y3": indicator.zhi_3, "deduct": f"-{d_qua}", "score": f"{s_qua:.2f}", "desc": _dim_desc("质量", s_qua)},
    ]

    return {
        "report_no": f"RPT-{indicator.batch_no}-{indicator.id:05d}",
        "ent": ent,
        "ind": indicator,
        "level_cn": lvl_cn,
        "conclusion": conclusion,
        "dimensions": dimensions,
        "region_display": format_region_display(ent.province, ent.city, ent.district),
        "extra_rows": extract_clean_archive_rows(ent),
    }


def _find_cn_font() -> str:
    """查找本机或容器内可用中文字体（Fail Fast 校验）"""
    candidates = [
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    raise RuntimeError("未找到系统可用中文字体文件")


def _draw_section_header(pdf: FPDF, title: str, right_note: str = ""):
    """绘制与网页卡片一致的章节标题栏"""
    pdf.set_x(pdf.l_margin)
    pdf.set_font("cn", size=11)
    pdf.set_text_color(15, 23, 42)
    if right_note:
        pdf.cell(pdf.epw * 0.65, 8, title, new_x="RIGHT", new_y="TOP", align="L")
        pdf.set_font("cn", size=8.5)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(pdf.epw * 0.35, 8, right_note, new_x="LMARGIN", new_y="NEXT", align="R")
    else:
        pdf.cell(pdf.epw, 8, title, new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(1)


def _draw_four_col_row(pdf: FPDF, k1: str, v1: str, k2: str, v2: str, widths=(32, 63, 32, 63), h=7.5):
    """绘制标准四列对称档案表格行（灰底标签列 + 白底数值列）"""
    w1, w2, w3, w4 = widths
    if pdf.get_y() + h > pdf.page_break_trigger:
        pdf.add_page()

    pdf.set_draw_color(203, 213, 225)  # #CBD5E1 边框色
    pdf.set_line_width(0.2)

    # 列 1：左标签
    pdf.set_fill_color(248, 250, 252)  # #F8FAFC 浅灰蓝表头色
    pdf.set_text_color(71, 85, 105)
    pdf.set_font("cn", size=8.5)
    pdf.cell(w1, h, f" {_clean_pdf_text(k1)}", border=1, fill=True, new_x="RIGHT", new_y="TOP", align="L")

    # 列 2：左数值
    pdf.set_fill_color(255, 255, 255)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(w2, h, f" {_clean_pdf_text(v1)[:34]}", border=1, fill=True, new_x="RIGHT", new_y="TOP", align="L")

    # 列 3：右标签
    pdf.set_fill_color(248, 250, 252)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(w3, h, f" {_clean_pdf_text(k2)}", border=1, fill=True, new_x="RIGHT", new_y="TOP", align="L")

    # 列 4：右数值
    pdf.set_fill_color(255, 255, 255)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(w4, h, f" {_clean_pdf_text(v2)[:34]}", border=1, fill=True, new_x="LMARGIN", new_y="NEXT", align="L")


def _draw_merged_multiline_row(pdf: FPDF, label: str, val_text: str, label_w=32, total_w=190):
    """绘制跨三列的多行自动换行单元格（用于核准经营范围）"""
    val_w = total_w - label_w
    clean_val = _clean_pdf_text(val_text)
    pdf.set_font("cn", size=8.5)

    lines = pdf.multi_cell(val_w - 4, 5.5, clean_val, split_only=True)
    num_lines = max(1, len(lines))
    row_h = max(8.0, num_lines * 5.5 + 3.0)

    if pdf.get_y() + row_h > pdf.page_break_trigger:
        pdf.add_page()

    x0, y0 = pdf.get_x(), pdf.get_y()
    pdf.set_draw_color(203, 213, 225)

    # 左侧灰底标签框
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(x0, y0, label_w, row_h, style="DF")
    pdf.set_text_color(71, 85, 105)
    pdf.set_xy(x0, y0 + (row_h - 5.5) / 2)
    pdf.cell(label_w, 5.5, f" {label}", border=0, align="L")

    # 右侧白底跨列内容框
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x0 + label_w, y0, val_w, row_h, style="DF")
    pdf.set_text_color(30, 41, 59)
    pdf.set_xy(x0 + label_w + 2, y0 + 1.5)
    pdf.multi_cell(val_w - 4, 5.5, clean_val, border=0, align="L")

    pdf.set_xy(x0, y0 + row_h)


def generate_report_pdf(indicator) -> tuple[bytes, str]:
    """生成与网页端表格样式完全一致的 PDF 风险评估报告（FR-03-04）"""
    ctx = build_report_context(indicator)
    ent, ind = ctx["ent"], ctx["ind"]
    font_path = _find_cn_font()

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(10, 12, 10)  # 左右边距各 10mm，内容总宽 190mm
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.add_font("cn", "", font_path)

    # ==================== 顶部报告标题与评级概览 ====================
    pdf.set_font("cn", size=15)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(190, 9, "企业风险评估尽调报告", new_x="LMARGIN", new_y="NEXT", align="C")

    scored_time = ind.scored_at.strftime("%Y-%m-%d %H:%M") if getattr(ind, "scored_at", None) else "已核验归档"
    pdf.set_font("cn", size=9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(
        190, 6,
        f"报告编号：{ctx['report_no']}   |   综合得分：{ind.total_risk_score} 分（{ctx['level_cn']}）   |   评估时间：{scored_time}",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(3)

    # ==================== 表一：一、评估主体工商档案（四列对称表格） ====================
    _draw_section_header(pdf, "一、评估主体工商档案")

    base_rows = [
        ("企业名称", ent.firm_name, "统一社会信用代码", ent.usc_code or "-"),
        ("法定代表人", ent.legal_rep or "-", "经营状态", ent.get_ope_status_display()),
        ("企业类型", ent.firm_type or "-", "注册资本", f"{ent.reg_cap} 万元"),
        ("所属行业", ent.ind_econ_name or "-", "所属地区", ctx["region_display"]),
    ]
    for k1, v1, k2, v2 in base_rows:
        _draw_four_col_row(pdf, k1, v1, k2, v2)

    # 渲染清洗后的宽表扩展字段行（组织机构代码、工商注册号、开业/核准/注销日期、坐标、唯一编码等）
    for row in ctx["extra_rows"]:
        _draw_four_col_row(pdf, row[0]["label"], row[0]["value"], row[1]["label"], row[1]["value"])

    # 底部跨列渲染核准经营范围（自动清除 ** 星号并折行）
    _draw_merged_multiline_row(pdf, "核准经营范围", ent.business_scope or "未登记具体经营范围")
    pdf.ln(5)

    # ==================== 表二：二、四维风险量化评分与底层指标明细（七列表格） ====================
    _draw_section_header(pdf, "二、四维风险量化评分与底层指标明细", f"评估时间：{scored_time}")

    col_w = (24, 38, 22, 22, 22, 27, 35)  # 7 列总宽 = 190mm
    headers = ("评估维度", "核心考核指标", "近 1 年次数", "近 2 年次数", "近 3 年次数", "重加权扣分", "维度得分 (满分25)")

    # 表头行
    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(203, 213, 225)
    pdf.set_text_color(51, 65, 85)
    pdf.set_font("cn", size=8.5)
    for idx, h_text in enumerate(headers):
        nxt_x = "LMARGIN" if idx == len(headers) - 1 else "RIGHT"
        nxt_y = "NEXT" if idx == len(headers) - 1 else "TOP"
        pdf.cell(col_w[idx], 8, h_text, border=1, fill=True, new_x=nxt_x, new_y=nxt_y, align="C")

    # 四维度数据行
    for d in ctx["dimensions"]:
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(col_w[0], 7.5, d["name"], border=1, fill=True, new_x="RIGHT", new_y="TOP", align="C")
        pdf.cell(col_w[1], 7.5, d["metric"], border=1, fill=True, new_x="RIGHT", new_y="TOP", align="C")
        pdf.cell(col_w[2], 7.5, str(d["y1"]), border=1, fill=True, new_x="RIGHT", new_y="TOP", align="C")
        pdf.cell(col_w[3], 7.5, str(d["y2"]), border=1, fill=True, new_x="RIGHT", new_y="TOP", align="C")
        pdf.cell(col_w[4], 7.5, str(d["y3"]), border=1, fill=True, new_x="RIGHT", new_y="TOP", align="C")

        # 扣分列（红色字体）
        pdf.set_text_color(220, 38, 38)
        pdf.cell(col_w[5], 7.5, d["deduct"], border=1, fill=True, new_x="RIGHT", new_y="TOP", align="C")

        # 维度得分列（蓝色字体）
        pdf.set_text_color(37, 99, 235)
        pdf.cell(col_w[6], 7.5, d["score"], border=1, fill=True, new_x="LMARGIN", new_y="NEXT", align="C")

    # 汇总行（前 5 列合并为 128mm，后 2 列合并为 62mm）
    pdf.set_fill_color(248, 250, 252)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(sum(col_w[:5]), 8.5, "综合风险评估总分（满分 100 分）： ", border=1, fill=True, new_x="RIGHT", new_y="TOP", align="R")

    if ind.risk_level == "H":
        pdf.set_text_color(192, 57, 43)
    elif ind.risk_level == "M":
        pdf.set_text_color(183, 121, 31)
    else:
        pdf.set_text_color(30, 123, 69)
    pdf.cell(
        sum(col_w[5:]), 8.5,
        f"{ind.total_risk_score} 分（{ctx['level_cn']}）",
        border=1, fill=True, new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(5)

    # ==================== 表三：三、综合尽调综述与授信风控建议 ====================
    _draw_section_header(pdf, "三、综合尽调综述与授信风控建议")
    _draw_merged_multiline_row(pdf, "尽调综述与建议", ctx["conclusion"], label_w=32, total_w=190)

    buf = io.BytesIO()
    pdf.output(buf)
    filename = f"{ent.firm_name}-风险评估尽调报告.pdf"
    return buf.getvalue(), quote(filename)
