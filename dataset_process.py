# -*- coding: utf-8 -*-
"""数据集质量探查：对照字段定义表逐字段核对含义/类型/取值，输出数据预览、缺失值、异常值与分布统计。

用法：python dataset_process.py     （数据与定义表位于同目录 dataset/ 下）
"""
import re
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")  # 避免 Windows 控制台编码导致输出中断

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 40)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

DATA_DIR = Path(__file__).parent / "dataset"
DATASETS = [
    ("企业基准风险信息", "ads_company_rating_basis_1w.csv", "企业基准风险信息字段表.xlsx"),
    ("企业工商基本信息", "dwd_essential_info_commercial_reg_info_1w.csv", "企业基本信息字段定义.xlsx"),
]

# ---- 口径与规则配置（依据字段定义表整理）----
NULL_TOKENS = {"", "null", "none", "nan", "na", "n/a", "-", "--", "/", "无", "未知", "0000-00-00"}
NUM_STRIP = re.compile(r"[^0-9.\-]")
UUID_RE = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
USC_RE = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}$")
DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")
NUM_LIKE = re.compile(r"^-?[\d,]+(\.\d+)?$")
KEY_COLS = {"id", "firm_eid", "firm_id"}
# 声明 string 但实为标识/编码：看格式、长度、前导零，不做数值统计
CODE_COLS = {"usc_code", "reg_no", "org_no", "tax_no", "legal_rep_id", "ind_econ_code",
             "reg_agency_area_code", "usc_code_area_code", "ope_addr_code", "reg_addr_code", "district"}
CODE_LEN = {"usc_code": 18, "reg_no": 15, "org_no": 9, "legal_rep_id": 32, "district": 6,
            "reg_agency_area_code": 6, "usc_code_area_code": 6}
ENUM_RULES = {"firm_category": {"E", "P"}, "ope_status": {"1", "2"}, "is_history": {"0", "1"}}
COORD_RANGE = {"bd_longitude": (73, 136), "gd_longitude": (73, 136), "bd_latitude": (3, 54), "gd_latitude": (3, 54)}
COORD_PLACEHOLDER = "-1"                       # 经纬度取 -1 表示无坐标（伪缺失）
MONO_PREFIX = ("cai", "s_an", "li_an", "zhi")  # 近1/2/3年窗口计数应满足 近1年 ≥ 近2年 ≥ 近3年
DATE_LOGIC = [("est_date", "cancel_date"), ("est_date", "rev_date"), ("est_date", "close_date"),
              ("est_date", "appr_date"), ("open_date", "close_date")]
EQ_GROUPS = [("id", "firm_eid", "firm_id"), ("legal_rep_type", "legal_rep_category"),
             ("reg_agency_area_code", "usc_code_area_code", "district")]
COORD_PAIRS = [("bd_longitude", "gd_longitude"), ("bd_latitude", "gd_latitude")]
USC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
USC_WEIGHT = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]


def f(x):
    return "-" if pd.isna(x) else f"{x:,.4g}"


def section(title):
    print("\n" + "=" * 112 + f"\n【{title}】\n" + "=" * 112)


def is_missing(s):
    return s.str.lower().isin(NULL_TOKENS)


def clean(s):
    return s.where(~is_missing(s))                       # 归一化缺失（含占位符）


def to_num(s):
    c = s.str.replace(NUM_STRIP, "", regex=True)         # 去单位、千分位等噪声
    return pd.to_numeric(c.mask(c.isin({"", "-", ".", "--"})), errors="coerce")


def to_date(s):
    return pd.to_datetime(s, errors="coerce", format="mixed")


def usc_valid(code):
    """GB32100 统一社会信用代码校验位"""
    if len(code) != 18 or not USC_RE.match(code):
        return False
    total = sum(USC_CHARS.index(c) * w for c, w in zip(code[:17], USC_WEIGHT))
    return USC_CHARS[(31 - total % 31) % 31] == code[17]


def declare_kind(dtype):
    d = str(dtype).lower()
    if any(k in d for k in ("int", "decimal", "float", "numeric", "bigint")):
        return "NUM"
    if "date" in d or "time" in d:
        return "DATE"
    if "list" in d:
        return "LIST"
    return "STR"


def detect_kind(col, v, declared):
    if v.empty:
        return "EMPTY"
    if col in KEY_COLS or v.str.match(UUID_RE).mean() > 0.9:
        return "KEY"
    if declared == "DATE" or v.str.match(DATE_RE).mean() > 0.9:
        return "DATE"
    if col in COORD_RANGE:
        return "COORD"
    if declared == "NUM":
        return "NUM"
    if col in CODE_COLS:
        return "CODE"
    if v.nunique() <= 30:
        return "CAT"
    if to_num(v).notna().mean() > 0.95:
        return "NUM"
    return "TEXT" if v.str.len().mean() > 40 else "NAME"


def num_stats(col, cn, v, declared, dtype, base):
    """数值形态：分布、离群、负值/零值、解析失败"""
    x = to_num(v)
    ok, alerts = x.notna(), []
    q1, q3, iqr = x.quantile(0.25), x.quantile(0.75), x.quantile(0.75) - x.quantile(0.25)
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out, neg = x[(x < lo) | (x > hi)], (x < 0)
    stat = (f"min={f(x.min())} P50={f(x.median())} P75={f(q3)} max={f(x.max())} 均值={f(x.mean())} "
            f"σ={f(x.std())} 零值={int((x == 0).sum())} 负值={int(neg.sum())} IQR离群={len(out)}")
    if ok.mean() < 1:
        alerts.append(f"{col}({cn}) {int((~ok).sum())} 条无法解析为数值，样例：{v[~ok].head(3).tolist()}")
    if declared == "STR" and col not in CODE_COLS and dtype:
        unit = v[~v.str.match(NUM_LIKE)]
        alerts.append(f"{col}({cn}) 定义为 {dtype}，实际为数值，类型与取值不符"
                      + (f"；{len(unit)} 条含单位/文字（如 {unit.head(3).tolist()}），需清洗" if len(unit) else ""))
    if neg.any():
        alerts.append(f"{col}({cn}) 存在 {int(neg.sum())} 条负值（最小 {f(x.min())}），业务口径上不应为负")
    if len(out) / max(base, 1) >= 0.01:
        alerts.append(f"{col}({cn}) IQR 离群 {len(out)} 条（{len(out) / base * 100:.1f}%，围栏 [{f(lo)}, {f(hi)}]），"
                      f"极大值 top：{x.sort_values(ascending=False).head(5).tolist()}")
    row = {"字段": col, "中文释义": cn, "有效值": int(ok.sum()), "最小": x.min(), "P25": q1, "中位": x.median(),
           "P75": q3, "最大": x.max(), "均值": x.mean(), "标准差": x.std(), "负值数": int(neg.sum()),
           "零值数": int((x == 0).sum()), "IQR离群数": len(out), "离群率%": round(len(out) / base * 100, 2)}
    return stat, row, alerts


def profile_column(col, s, cn, dtype):
    miss = is_missing(s)
    v, base = s[~miss], max(len(s), 1)
    declared = declare_kind(dtype)
    actual = detect_kind(col, v, declared)
    num_row, cat_tab, alerts, extra = None, None, [], ""

    if actual == "EMPTY":
        extra = "整列无有效值（占位/未落库），需确认是否为预期留空"
    elif actual == "KEY":
        dup = int(v.duplicated().sum())
        extra = f"主键重复={dup} 长度={sorted(set(v.str.len()))}"
        if dup:
            alerts.append(f"{col}({cn}) 唯一标识出现 {dup} 条重复，违反主键定义")
    elif actual == "CODE":
        L = v.str.len()
        mode_len = L.mode().iloc[0] if len(L) else 0
        bad_len = int((L != CODE_LEN.get(col, mode_len)).sum())
        lead0 = int(v.str.startswith("0").sum())
        extra = f"主流长度={mode_len} 长度异常={bad_len} 前导零={lead0}"
        if col == "usc_code":
            bad = v[[not usc_valid(c) for c in v]]
            extra += f" 校验位不合法={len(bad)}"
            if len(bad):
                alerts.append(f"{col}({cn}) {len(bad)} 条不满足 GB32100 校验位规则，样例：{bad.head(3).tolist()}")
        if bad_len:
            std = CODE_LEN.get(col)
            alerts.append(f"{col}({cn}) {bad_len} 条长度不等于标准位数{std if std else '（无标准位数，取众数）'}，"
                          f"长度分布：{L.value_counts().head(5).to_dict()}")
        if lead0:
            alerts.append(f"{col}({cn}) {lead0} 条以 0 开头，读取时若按数值解析将丢失前导零，必须保持字符串类型")
    elif actual == "COORD":
        lo, hi = COORD_RANGE[col]
        ph = int((v == COORD_PLACEHOLDER).sum())
        x = to_num(v[v != COORD_PLACEHOLDER])
        bad = int(((x < lo) | (x > hi)).sum())
        extra = (f"区间[{f(x.min())}, {f(x.max())}] 中位={f(x.median())} 占位值(-1)={ph} "
                 f"超出中国范围={bad}" if len(x) else f"占位值(-1)={ph}")
        if ph:
            alerts.append(f"{col}({cn}) {ph} 条以 {COORD_PLACEHOLDER} 占位表示无坐标，属伪缺失，应转为空值")
        if bad:
            alerts.append(f"{col}({cn}) {bad} 条超出合理区间 [{lo}, {hi}]")
    elif actual == "NUM":
        extra, num_row, alerts = num_stats(col, cn, v, declared, dtype, base)
    elif actual == "DATE":
        d = to_date(v)
        bad, future = int(d.isna().sum()), int((d > pd.Timestamp.today()).sum())
        extra = (f"最早={d.min().date() if d.notna().any() else '-'} "
                 f"最晚={d.max().date() if d.notna().any() else '-'} 解析失败={bad} 晚于当前={future}")
        if bad:
            alerts.append(f"{col}({cn}) {bad} 条日期无法解析，样例：{v[d.isna()].head(3).tolist()}")
        if future:
            alerts.append(f"{col}({cn}) {future} 条日期晚于当前日期，样例：{v[d > pd.Timestamp.today()].head(3).tolist()}")
    elif actual == "CAT":
        vc = v.value_counts()
        cat_tab = pd.DataFrame({col: vc.index, "频数": vc.values, "占比%": (vc.values / base * 100).round(2)}).head(20)
        extra = " | ".join(f"{k}({n / base * 100:.1f}%)" for k, n in vc.head(5).items())
        allow = ENUM_RULES.get(col)
        if allow:
            bad = v[~v.isin(allow)]
            extra += f" | 定义域外={len(bad)}"
            if len(bad):
                alerts.append(f"{col}({cn}) {len(bad)} 条取值超出定义范围 {sorted(allow)}：{bad.value_counts().to_dict()}")
    else:
        L = v.str.len()
        dup = int(v.duplicated().sum())
        long = v[L > max(3 * L.median(), 15)] if actual == "NAME" else v.iloc[:0]
        extra = f"均长={f(L.mean())} 最长={int(L.max())} 重复值={dup}" + (f" 超长值={len(long)}" if len(long) else "")
        if dup / base > 0.5:
            alerts.append(f"{col}({cn}) 非空值中 {dup} 条重复（{dup / base * 100:.1f}%），区分度低")
        if len(long):
            alerts.append(f"{col}({cn}) {len(long)} 条长度显著超常（>3×中位长度），疑似内容错位，"
                          f"样例：{long.head(2).tolist()}")

    flag = ((declared == "NUM" and actual not in ("NUM", "EMPTY"))
            or (declared == "DATE" and actual not in ("DATE", "EMPTY"))
            or (declared == "STR" and actual == "NUM" and col not in CODE_COLS))
    return ({"字段": col, "中文释义": cn, "定义类型": dtype or "定义表未定义", "实际形态": actual,
             "类型核对": "未定义" if not dtype else ("不一致" if flag else "一致"),
             "缺失数": int(miss.sum()), "缺失率%": round(miss.sum() / base * 100, 2),
             "唯一值": int(v.nunique()), "关键统计": extra},
            num_row, cat_tab, alerts)


def logic_checks(df):
    """跨字段业务逻辑校验：时间窗单调性、日期先后、编码派生与一致性、坐标量纲"""
    out = []
    for p in MONO_PREFIX:
        cols = [f"{p}_{i}" for i in (1, 2, 3) if f"{p}_{i}" in df]
        if len(cols) == 3:
            x = df[cols].apply(to_num)
            bad = int(((x[cols[0]] < x[cols[1]]) | (x[cols[1]] < x[cols[2]])).sum())
            means = x.mean()
            sim = abs(means.max() - means.min()) < 0.1            # 三窗口均值几乎相同
            out.append(f"{cols} 时间窗单调性（近1年应≥近2年应≥近3年）：违反 {bad} 条（{bad / len(df) * 100:.1f}%）"
                       + (f"；且三窗口均值 {means.tolist()} 基本一致，疑未按时间窗区分" if sim else "")
                       if bad else f"{cols} 时间窗单调性一致")
    for a, b in DATE_LOGIC:
        if {a, b} <= set(df):
            da, db = to_date(clean(df[a])), to_date(clean(df[b]))
            bad = int((db < da).sum())
            if bad:
                out.append(f"{b} 早于 {a} 共 {bad} 条（{bad / len(df) * 100:.2f}%），日期逻辑异常")
    for cols in EQ_GROUPS:
        cols = list(cols)
        if set(cols) <= set(df):
            sub = df[cols].apply(clean).dropna()
            if len(sub):
                base = sub.iloc[:, 0]
                bad = int((sub.ne(base, axis=0)).any(axis=1).sum())
                out.append(f"{'/'.join(cols)} 应一致：{len(sub)} 条有值，不一致 {bad} 条（{bad / len(sub) * 100:.1f}%）"
                           + (f"，样例 {sub[~sub.eq(base, axis=0).all(axis=1)].head(2).to_dict('records')}" if bad else ""))
    if {"usc_code", "org_no", "reg_agency_area_code"} <= set(df):
        u, o, r = clean(df["usc_code"]), clean(df["org_no"]), clean(df["reg_agency_area_code"])
        m = u.str.len().eq(18) & o.notna()
        bad = int((u[m].str[8:17] != o[m]).sum())
        out.append(f"usc_code[8:17] 与 org_no 派生关系：可比 {int(m.sum())} 条，不一致 {bad} 条")
        m2 = u.str.len().eq(18) & r.notna()
        bad2 = int((u[m2].str[2:8] != r[m2]).sum())
        out.append(f"usc_code[2:8]（登记机关区划）与 reg_agency_area_code：可比 {int(m2.sum())} 条，不一致 {bad2} 条")
    for a, b in COORD_PAIRS:
        if a in df and b in df:
            xa = to_num(clean(df[a]).mask(df[a] == COORD_PLACEHOLDER))
            xb = to_num(clean(df[b]).mask(df[b] == COORD_PLACEHOLDER))
            d = (xa - xb).abs()
            far = int((d > 0.01).sum())
            out.append(f"{a} 与 {b}（不同地图源）偏差：>0.01度(≈1km) 共 {far} 条，最大偏差 {f(d.max())} 度")
    dup = int(df.duplicated().sum())
    out.append(f"整行完全重复 {dup} 条" if dup else "无整行完全重复记录")
    return out


def run(name, csv, xlsx):
    df = pd.read_csv(DATA_DIR / csv, dtype=str, keep_default_na=False).apply(lambda s: s.str.strip())
    df.columns = [c.strip() for c in df.columns]
    defs = pd.read_excel(DATA_DIR / xlsx)
    dmap = {str(r["字段名"]).strip(): (str(r["中文释义"]).strip(), str(r["数据类型"]).strip())
            for _, r in defs.iterrows()}

    section(f"{name}｜字段核对（数据 vs 定义表）")
    print(f"数据文件 {csv}：{df.shape[0]} 行 × {df.shape[1]} 列；定义表 {xlsx}：{len(dmap)} 个字段")
    print(f"定义表有而数据缺失的字段：{sorted(set(dmap) - set(df)) or '无'}")
    print(f"数据有而定义表未定义的字段：{sorted(set(df) - set(dmap)) or '无'}（此类字段按取值自动判定形态）")
    print(f"字段排列顺序与定义表一致：{[c for c in df.columns if c in dmap] == [c for c in dmap if c in df.columns]}")

    section(f"{name}｜数据预览（前 3 条）")
    pv = df.head(3).T
    pv.insert(0, "中文释义", [dmap.get(c, ("-",))[0] for c in pv.index])
    print(pv.apply(lambda c: c.str.slice(0, 30)).to_string())

    rows, nums, cats, alerts = [], [], [], []
    for col in df.columns:
        cn, dtype = dmap.get(col, ("定义表未定义", ""))
        r, num, cat, al = profile_column(col, df[col], cn, dtype)
        rows.append(r)
        nums += [num] if num is not None else []
        cats += [cat] if cat is not None else []
        alerts += al

    section(f"{name}｜逐字段质量总览（缺失 / 唯一值 / 类型核对）")
    ov = pd.DataFrame(rows)
    print(ov.to_string(index=False))
    print(f"\n缺失率>50% 的字段（{int((ov['缺失率%'] > 50).sum())} 个）："
          f"{ov.loc[ov['缺失率%'] > 50, '字段'].tolist() or '无'}")
    print(f"整列空值字段：{ov.loc[ov['实际形态'] == 'EMPTY', '字段'].tolist() or '无'}")
    print(f"类型核对不一致字段：{ov.loc[ov['类型核对'] == '不一致', '字段'].tolist() or '无'}")

    if nums:
        section(f"{name}｜数值字段统计分析")
        print(pd.DataFrame(nums).to_string(index=False))
    if cats:
        section(f"{name}｜类别字段取值分布")
        for t in cats:
            print(f"\n—— {t.columns[0]}（{len(t)} 类，取 top20）")
            print(t.to_string(index=False))

    section(f"{name}｜异常值与取值告警")
    uniq = list(dict.fromkeys(alerts))
    print("\n".join("· " + a for a in uniq) if uniq else "· 未发现取值级异常")

    section(f"{name}｜跨字段业务逻辑校验")
    print("\n".join("· " + a for a in logic_checks(df)))
    return df


def cross_check(risk, reg):
    section("两表关联一致性核对（以 id 为关联键）")
    a, b = risk.set_index("id"), reg.set_index("id")
    common = a.index.intersection(b.index)
    print(f"风险表企业 {len(a)} 家 / 工商表企业 {len(b)} 家 / 可关联 {len(common)} 家；"
          f"仅在风险表 {len(a.index.difference(b.index))} 家，仅在工商表 {len(b.index.difference(a.index))} 家")
    m = a.loc[common].join(b.loc[common], rsuffix="_g")
    for ca, cb, cn in [("name", "firm_name", "企业名称"), ("f_ren", "legal_rep", "法定代表人"),
                       ("zhuce_money", "reg_cap", "注册资本"), ("jing_fan", "ope_scope", "经营范围")]:
        if ca not in m or cb not in m:
            continue
        x, y = clean(m[ca]), clean(m[cb])
        both = x.notna() & y.notna()
        if not both.any():
            print(f"· {cn}：两表同时有值 0 条（{ca} 缺失严重，无法比对）")
            continue
        if ca == "zhuce_money":
            diff = (to_num(x[both]) - to_num(y[both])).abs() > 0.01
        else:
            diff = x[both].str.replace(r"\s", "", regex=True) != y[both].str.replace(r"\s", "", regex=True)
        print(f"· {cn}：可比对 {int(both.sum())} 条，不一致 {int(diff.sum())} 条（{diff.mean() * 100:.1f}%）"
              f"｜样例 {m.loc[both, [ca, cb]][diff].head(2).to_dict('records')}")
    if {"qiye_type", "firm_type"} <= set(m):
        pair = (m["qiye_type"] + " -> " + m["firm_type"]).value_counts().head(8)
        print(f"· 企业类型文本(风险表) 与 企业类型编码(工商表) 映射 top8：\n{pair.to_string()}")


if __name__ == "__main__":
    frames = [run(*ds) for ds in DATASETS]
    cross_check(*frames)
    print("\n探查完成。")
