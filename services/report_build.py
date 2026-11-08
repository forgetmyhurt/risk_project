import io
from pathlib import Path
from urllib.parse import quote
from fpdf import FPDF

LEVEL_MAP = {"L": "低风险", "M": "中风险", "H": "高风险"}

def _dim_desc(name: str, score: float) -> str:
    """按维度得分区间生成说明文字（FR-03-02）"""
    if score >= 22:
        return f"{name}维度得分 {score:.2f}/25.00，近三年相关涉诉与执行记录极少，表现良好。"
    if score >= 15:
        return f"{name}维度得分 {score:.2f}/25.00，存在一定频次的司法或经营风险记录，建议持续关注。"
    return f"{name}维度得分 {score:.2f}/25.00，相关风险事件频发，扣分较多，建议重点核查。"

def build_report_context(indicator) -> dict:
    """组装报告四章节数据（结论 / 维度分析 / 指标明细 / 档案信息）"""
    ent = indicator.enterprise
    s_fin = float(indicator.score_fin)
    s_ope = float(indicator.score_ope)
    s_com = float(indicator.score_com)
    s_qua = float(indicator.score_qua)
    total = float(indicator.total_risk_score)
    lvl_cn = LEVEL_MAP.get(indicator.risk_level, "低风险")

    if indicator.risk_level == "L":
        conclusion = f"该企业综合风险得分为 {total:.1f} 分，评级为【{lvl_cn}】。整体资信与司法合规状况良好，可按常规流程开展授信或合作。"
    elif indicator.risk_level == "M":
        conclusion = f"该企业综合风险得分为 {total:.1f} 分，评级为【{lvl_cn}】。部分维度存在历史涉诉或立案记录，建议补充尽调材料并收紧风控额度。"
    else:
        conclusion = f"该企业综合风险得分为 {total:.1f} 分，评级为【{lvl_cn}】。司法诉讼或被执行风险突出，建议审慎介入或要求追加足额担保。"

    dimensions = [
        {"name": "财务风险", "score": s_fin, "items": f"近1/2/3年被裁判次数：{indicator.cai_1} / {indicator.cai_2} / {indicator.cai_3}", "desc": _dim_desc("财务", s_fin)},
        {"name": "经营风险", "score": s_ope, "items": f"近1/2/3年立案数：{indicator.s_an_1} / {indicator.s_an_2} / {indicator.s_an_3}", "desc": _dim_desc("经营", s_ope)},
        {"name": "合规风险", "score": s_com, "items": f"近1/2/3年被立案次数：{indicator.li_an_1} / {indicator.li_an_2} / {indicator.li_an_3}", "desc": _dim_desc("合规", s_com)},
        {"name": "质量风险", "score": s_qua, "items": f"近1/2/3年被执行次数：{indicator.zhi_1} / {indicator.zhi_2} / {indicator.zhi_3}", "desc": _dim_desc("质量", s_qua)},
    ]

    return {
        "report_no": f"RPT-{indicator.batch_no}-{indicator.id:05d}",
        "ent": ent,
        "ind": indicator,
        "level_cn": lvl_cn,
        "conclusion": conclusion,
        "dimensions": dimensions,
    }

def _find_cn_font() -> str:
    """查找本机或容器内可用中文字体（Fail Fast 校验）"""
    candidates = [
        # Linux 容器字体路径（Debian / Ubuntu / wqy）
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        # Windows 本地开发环境字体
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    raise RuntimeError("未找到系统可用中文字体文件")

def generate_report_pdf(indicator) -> tuple[bytes, str]:
    """生成 PDF 二进制流与下载文件名（FR-03-04）"""
    ctx = build_report_context(indicator)
    ent, ind = ctx["ent"], ctx["ind"]
    font_path = _find_cn_font()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("cn", "", font_path)
    w = pdf.epw  # 页面有效可用宽度

    def write_title(text: str):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("cn", size=12)
        pdf.cell(w, 9, text, new_x="LMARGIN", new_y="NEXT")

    def write_paragraph(text: str):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("cn", size=10)
        pdf.multi_cell(w, 7, text, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

    # 报告主标题
    pdf.set_font("cn", size=16)
    pdf.cell(w, 12, f"企业风险评估报告（{ctx['report_no']}）", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)

    # 一、评估结论
    write_title("一、评估结论")
    write_paragraph(
        f"企业名称：{ent.firm_name}\n"
        f"统一社会信用代码：{ent.usc_code or '-'}\n"
        f"综合得分：{ind.total_risk_score} 分    风险等级：{ctx['level_cn']}    评分批次：{ind.batch_no}\n"
        f"综述：{ctx['conclusion']}"
    )
    pdf.ln(2)

    # 二、四维度风险分析
    write_title("二、四维度风险分析")
    for d in ctx["dimensions"]:
        write_paragraph(f"· {d['name']}：{d['desc']}（{d['items']}）")
    pdf.ln(2)

    # 三、12 项原始风险指标明细
    write_title("三、12 项原始风险指标明细")
    write_paragraph(
        f"被裁判次数（近1/2/3年）：{ind.cai_1} / {ind.cai_2} / {ind.cai_3}\n"
        f"涉案立案数（近1/2/3年）：{ind.s_an_1} / {ind.s_an_2} / {ind.s_an_3}\n"
        f"被立案次数（近1/2/3年）：{ind.li_an_1} / {ind.li_an_2} / {ind.li_an_3}\n"
        f"被执行次数（近1/2/3年）：{ind.zhi_1} / {ind.zhi_2} / {ind.zhi_3}"
    )
    pdf.ln(2)

    # 四、企业工商档案信息
    write_title("四、企业工商档案信息")
    write_paragraph(
        f"法定代表人：{ent.legal_rep or '-'}    企业类别：{ent.get_firm_category_display()}    经营状态：{ent.get_ope_status_display()}\n"
        f"注册资本：{ent.reg_cap} 万元    成立日期：{ent.est_date or '-'}    所属地区：{ent.province}{ent.city}{ent.district}\n"
        f"行业名称：{ent.ind_econ_name or '-'}    登记机关：{ent.reg_agency or '-'}\n"
        f"经营范围：{(ent.business_scope or '-')[:300]}"
    )

    buf = io.BytesIO()
    pdf.output(buf)
    filename = f"{ent.firm_name}-{ctx['report_no']}.pdf"
    return buf.getvalue(), quote(filename)
