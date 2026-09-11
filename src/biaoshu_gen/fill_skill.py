"""标书模板填写 skill：按标签填空 / 表格填写 / 插入图片 的可复用原语。

设计要点（源自 fill 阶段 harness 实战脚本的提炼）：
- **标签锚定**而非魔法下标：以标签文本定位（如 "项目名称："，段首/段中皆可），模板微调不致错位；
- **填空不区分有无下划线**（blank op 已并入 label）：有下划线空位时值填*在线上*
  （带下划线格式的空白 run / 下划线字符 run 并保留余线），无下划线则值直接跟在标签后；
  标签后已是实义文本（已填过/正文）的命中自动跳过——同文本多段全填且不重复填；
- **图片**：WEBP 伪装 .jpg 时机械转码 PNG（不读取内容）；插图带居中与可选图注。

供 fill 阶段节点与 harness 兜底 agent 直接 import 使用（工作区内会自动放置本文件副本）。
"""
import copy as _copy
import os
import re

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.text.paragraph import Paragraph

UNDERLINE_CHARS = set("＿＿___―—-") - set("")  # 全角/半角下划线

# 全半角标点归一化表(一一对应单字符,归一化串下标与原文一致):LLM 回显宽度常漂移。
# 注意:这是"下标保持型"归一化;另有一套"仅判断包含"的空白折叠 _norm_ws,两者各司其职。
_WIDTH_NORM = str.maketrans({"（": "(", "）": ")", "：": ":", "，": ",", "；": ";"})

# 标签之后的合法边界：分隔符/括号/空白/段末/下划线字符（防 "投标人" 误中 "投标人地址"）
_BOUNDARY_CHARS = set("：:（）() \t，、；") | UNDERLINE_CHARS
# 标签后的跳过集 = 边界集中的非下划线成员(_fill_blank_after 的游走用;单一来源防漂移)
_SKIP_CHARS = "".join(sorted(_BOUNDARY_CHARS - UNDERLINE_CHARS))
_KEEP_TAIL = "＿＿"                              # 值落在下划线段上后保留的余线
# 空位 run 的值写到他处时如何清空（_slot_kind 语义的伴生规则，单一来源）：
# space(带下划线纯空白)整清空——值已带格式;line(下划线字符段)留余线维持版式
_CLEAR_BY_KIND = {"space": "", "line": _KEEP_TAIL}
# 括号占位「（xxx）」检测（_is_fill_candidate 与 replace 吸收判定共用;{1,20} 容常规占位）
_PAREN_PLACEHOLDER = re.compile(r"[（(][^（）()]{1,20}[）)]")


def _slot_kind(run) -> str | None:
    """run 属于哪种下划线填空位:「space」=带下划线的纯空白 run、「line」=纯下划线
    字符段、None=普通文本。空位语义的唯一定义点(预填/blank/label/before-label 共用)。"""
    t = run.text or ""
    if not t:
        return None
    if not t.strip():
        return "space" if _is_underlined(run) else None
    return "line" if set(t.strip()) <= UNDERLINE_CHARS else None


def _para_spans(p) -> list[tuple[int, int, object]]:
    """段落 run -> 字符区间 [(start,end,run)](_fill_blank_after 与 replace_in_para 共用)。"""
    spans = []
    start = 0
    for r in p.runs:
        t = r.text or ""
        spans.append((start, start + len(t), r))
        start += len(t)
    return spans


def _norm_ws(s: str) -> str:
    """空白归一化(\xa0→空格并折叠连续空白);仅供'是否包含'类匹配,不保下标。"""
    return " ".join(s.replace("\xa0", " ").split())


def _find_all(s: str, sub: str) -> list[tuple[int, int]]:
    out = []
    i = s.find(sub)
    while i >= 0:
        out.append((i, i + len(sub)))
        i = s.find(sub, i + len(sub))
    return out


def _has_fill_slot(p: Paragraph) -> bool:
    """段落是否真实存在下划线填空位（下划线空白 run 或下划线字符 run）；无则跳过不硬插。"""
    return any(_slot_kind(r) is not None for r in p.runs)


def _is_underlined(run) -> bool:
    rPr = run._element.rPr
    if rPr is None:
        return False
    u = rPr.find(qn("w:u"))
    return u is not None and u.get(qn("w:val")) == "single"


def find_para(doc, prefix: str) -> Paragraph:
    """按文本前缀定位段落；找不到抛 RuntimeError（带提示便于 harness 自纠）。"""
    for p in doc.paragraphs:
        if p.text.strip().startswith(prefix):
            return p
    raise RuntimeError(f"找不到以 {prefix!r} 开头的段落；请核对模板文本")


def _fill_blank_in_para(p: Paragraph, value: str) -> None:
    """在单个段落的填空线上填 value（保留下划线格式，不追加到线后）。"""
    blanks = [r for r in p.runs if r.text and not r.text.strip()]
    underlined = [r for r in blanks if _is_underlined(r)]
    if underlined:
        underlined[0].text = value
        for r in blanks:                       # 其余空白 run 清空（避免重复落值）
            if r is not underlined[0]:
                r.text = ""
        return
    for r in p.runs:                            # 下划线字符 run（＿＿＿/___）
        t = (r.text or "").strip()
        if t and set(t) <= UNDERLINE_CHARS:
            r.text = f"{value}{_KEEP_TAIL}"     # 值落在线上并保留余线
            return
    # 无空白也无下划线字符：复制末 run 格式插入带下划线的值 run（位置在段内，非段后附加）
    new_r = p.add_run(f" {value} ")
    last = p.runs[-2] if len(p.runs) >= 2 else p.runs[0]   # 复制标签 run 格式
    if last is not None and last._element.rPr is not None:
        new_r._element.insert(0, _copy.deepcopy(last._element.rPr))
    rPr = new_r._element.get_or_add_rPr()
    u = rPr.find(qn("w:u"))
    if u is None:
        u = rPr.makeelement(qn("w:u"), {})
        rPr.append(u)
    u.set(qn("w:val"), "single")


def fill_label_blank(doc, label: str, value: str) -> int:
    """段内**任意位置**按标签填其后的填空（含段中部，如「编号：__ 名称：__」同段），返回填写处数。

    label op 的底层原语（blank op 已并入）：有下划线空位值落线上留余线，
    无下划线则值直接跟在标签后；标签后已是实义文本（已填过/正文）的命中自动跳过。
    标签边界护栏同预填：标签前须是段首/分隔符/括号/空白/下划线，防前缀误中。
    """
    n = 0
    label_n = label.translate(_WIDTH_NORM)      # 模型回显宽度漂移:全半角归一化后匹配
    for p in doc.paragraphs:
        text_n = p.text.translate(_WIDTH_NORM)  # 1:1 映射,归一化下标=原文下标
        pos = 0
        while True:
            idx = text_n.find(label_n, pos)
            if idx < 0:
                break
            end = idx + len(label)
            pos = end                          # 先推进再校验:护栏失败也不至于原地重find
            if idx > 0 and text_n[idx - 1] not in _BOUNDARY_CHARS:
                continue                       # 边界不符（如「分包号」误中「包号」）
            if end < len(text_n) and text_n[end] not in _BOUNDARY_CHARS:
                continue                       # 段首匹配也须验证后边界（「投标人地址」≠「投标人」）
            if _fill_blank_after(p, end, value):
                n += 1
                text_n = p.text.translate(_WIDTH_NORM)   # 段文本已变,重找后续标签
                pos = end + len(value)
    return n


def _fill_blank_after(p: Paragraph, q: int, value: str) -> bool:
    """在段落第 q 个字符处起填空：跳过边界符（冒号/括号/空白）后填 value。

    落位不区分有无下划线（blank op 并入 label 后的统一语义）：
    - 下划线空位（字符段/段中 span/带下划线的纯空白 run）：值落在线上并保留余线；
    - 无下划线（标签后直接空到段末）：值直接接在段末，复制邻近 run 格式；
    - 标签后已是实义文本（已填过/正文/下一个标签）：不填返回 False，调用方跳下一处。
    """
    spans = _para_spans(p)
    total = spans[-1][1] if spans else 0

    def _run_at(pos: int):
        for s, e, r in spans:
            if s <= pos < e or (pos == s == e and not (r.text or "")):
                return s, e, r
        return None

    # 跳过标签后的边界符(LLM 常丢冒号:「采购代理编号」对「采购代理编号：__」);
    # 但空位本身就是下划线空白 run("space"),不可跳过——直接落值。
    while q < total and p.text[q] in _SKIP_CHARS:
        hit = _run_at(q)
        if hit is not None and _slot_kind(hit[2]) == "space":
            hit[2].text = value                 # 与 _fill_blank_in_para 一致:值即整线
            return True
        q += 1

    if q >= total:                              # 标签(+边界符)即段末:值直接跟在段末
        new_r = p.add_run(value)
        last = next((r for r in reversed(p.runs) if (r.text or "").strip()), None)
        if last is not None and last._element.rPr is not None:
            new_r._element.insert(0, _copy.deepcopy(last._element.rPr))
        return True
    hit = _run_at(q)
    if hit is None:
        return False
    s, _, r = hit
    t = r.text or ""
    off = q - s
    m = re.match("[_＿]+", t[off:])             # 段中/至 run 尾的下划线段均可
    if m:
        r.text = t[:off] + value + _KEEP_TAIL + t[off + m.end():]
        return True
    if not t and q == s:                        # 空 run 空位
        r.text = value
        return True
    return False                                # 实义文本:已填过/正文,跳过


def fill_blank_before_label(doc, label: str, value: str) -> int:
    """填「空位在标签前」形态：__(标签)——下划线空位 run 后紧跟括号注记，
    且括号内容**恰为** label 单一标签（商务部分的主要文体，如
    「我系参加__（项目名称），采购计划编号__」）。

    多标签并列（如「（项目名称、政府采购编号、采购代理编号）」）归属不明，不填；
    括号内容须与 label 全等，防「（采购人单位名称）」误中「（单位名称）」。
    填值后**清除紧随的「(label)」注记**（feedback #87）：值已表达语义，保留会叠读成
    「某某项目（项目名称）的磋商邀请」；同 run 内仅删首个括号对，其余文本不动。
    """
    n = 0
    for p in doc.paragraphs:
        runs = p.runs
        for i in range(len(runs) - 1):
            kind = _slot_kind(runs[i])
            if kind is None:
                continue                        # 非空位 run 不动
            m = re.match(r"\s*[（(]([^（）()]+)[）)]", runs[i + 1].text or "")
            if m and m.group(1).strip() == label:
                runs[i].text = value + _CLEAR_BY_KIND[kind]
                runs[i + 1].text = runs[i + 1].text[m.end():]   # 命中即首个括号对,直接切掉
                n += 1
    return n


def fill_all_blanks(doc, prefix: str, value: str) -> int:
    """把**所有**以 prefix 开头的段落的填空线都填上 value，返回填写段数（预填已知值用）。

    两道护栏（区别于 blank op 的 fill_blank，预填宁可少填也不可错填）：
    - 标签边界：prefix 之后须是分隔符/括号/空白/段末，避免 "投标人" 误中 "投标人地址"；
    - 空位门槛：段落须真实存在下划线填空位，无空位段落不硬插值（防 "投标人地址：无" 被塞值）。
    """
    n = 0
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix):]
        if rest and rest[0] not in _BOUNDARY_CHARS:
            continue
        if not _has_fill_slot(p):
            continue
        _fill_blank_in_para(p, value)
        n += 1
    return n


def replace_in_para(doc, prefix: str, old: str, new: str) -> list[Paragraph]:
    """段内文本替换：命中**全部**以 prefix 开头的段落（模板同构段一次全覆盖，
    与 label 的填全部命中语义一致），返回命中段落列表。

    每段内只重写命中区间的 run，同段其余 run（下划线填空位等）保持不动。
    old 字面找不到时按全半角标点归一化重试（LLM 常把模板半角括号写成全角；
    映射为一一对应单字符,归一化串下标可直接映射回原文）。段内全部命中从右往左
    依次改写,避免下标位移;spans 只需构建一次——右侧改写不影响左侧命中的区间。
    """
    hits = [p for p in doc.paragraphs if p.text.strip().startswith(prefix)]
    if not hits:
        raise RuntimeError(f"找不到以 {prefix!r} 开头的段落；请核对模板文本")
    absorb_slot = _PAREN_PLACEHOLDER.match(old.strip())   # 括号占位:连前置空位一并吞并
    for p in hits:
        full = "".join(r.text for r in p.runs)
        matches = _find_all(full, old) \
            or _find_all(full.translate(_WIDTH_NORM), old.translate(_WIDTH_NORM))
        if not matches:
            continue                      # 同前缀但无此占位符的段落跳过,其余段落继续
        spans = _para_spans(p)
        for pos, end in reversed(matches):
            if absorb_slot:
                # feedback #87:「签字代表＿＿（姓名、职务）」形态,括号占位与其前下划线
                # 空位是同一填写点——只换括号会留下悬空空位。空位 run 按 _CLEAR_BY_KIND
                # 清空(纯空白整清/下划线字符留余线),紧邻即止。
                for s, e, r in spans:
                    if s <= pos - 1 < e and (r.text or ""):
                        kind = _slot_kind(r)
                        if kind in _CLEAR_BY_KIND:
                            r.text = _CLEAR_BY_KIND[kind]
                        break
            hit = [(s, e, r) for s, e, r in spans if s < end and e > pos
                   or (s == e and pos <= s < end)]         # 空 run 视为在 pos 处
            if not hit:
                continue
            s_first, _, r_first = hit[0]
            s_last, _, r_last = hit[-1]
            r_first.text = (r_first.text or "")[:pos - s_first] + new \
                + (r_last.text or "")[end - s_last:]
            for _, _, r in hit[1:]:
                r.text = ""
    return hits


def fill_cell(doc, table_idx: int, row: int, col: int, text: str):
    """填表格单元格（保留表格结构）；行不够时自动加行（货物清单等按需扩表）。"""
    table = doc.tables[table_idx]
    while len(table.rows) <= row:
        table.add_row()
    para = table.rows[row].cells[col].paragraphs[0]
    if para.runs:
        para.runs[0].text = text
        for r in para.runs[1:]:
            r.text = ""
    else:
        para.add_run(text)
    return para


def ensure_readable_img(path: str) -> str:
    """WEBP 伪装 .jpg 的文件 python-docx 无法嵌入：机械转码 PNG（不读取内容）。"""
    with open(path, "rb") as fh:
        head = fh.read(12)
    if head.startswith(b"RIFF"):
        from PIL import Image
        im = Image.open(path)
        tmp = os.path.join(os.path.dirname(os.path.abspath(path)),
                           "_conv_" + os.path.splitext(os.path.basename(path))[0] + ".png")
        im.save(tmp, "PNG")
        return tmp
    return path


def _new_para_after(p: Paragraph) -> Paragraph:
    new_p = _copy.deepcopy(p._p)
    p._p.addnext(new_p)
    np_ = Paragraph(new_p, p._parent)
    for r in np_.runs:
        r.text = ""
    return np_


def _insert_picture_after_para(p: Paragraph, img: str, width_inch: float = 5.6,
                               caption: str | None = None) -> Paragraph:
    """在指定段落之后插入居中图片（可选图注），返回链式续插锚段（图注或图片段）。"""
    np_ = _new_para_after(p)
    np_.alignment = 1                       # center
    r = np_.add_run()
    r.add_picture(ensure_readable_img(img), width=Inches(width_inch))
    last = np_
    if caption:
        cp = _new_para_after(np_)
        cr = cp.add_run(caption)
        cr.font.size = Pt(9)
        cp.alignment = 1
        last = cp
    return last


def insert_picture_after(doc, prefix: str, img: str, width_inch: float = 5.6,
                         caption: str | None = None) -> Paragraph:
    """在 prefix 段落之后插入居中图片（可选图注），返回可继续链式插入的锚段。"""
    return _insert_picture_after_para(find_para(doc, prefix), img, width_inch, caption)


def insert_picture_into_frame(doc, row_keyword: str, img: str,
                              width_inch: float = 4.8) -> Paragraph:
    """把图片插进粘贴框表格的指定行（按行内文字定位），行内标签文字保留在图上方。

    模板的证照复印件位是单元格文字为「xxx 复印件」的单列框表（#89：身份证
    曾被插在框外段后、框空置且自创图注重读）。图落格内而非框外；行内已有图
    则跳过（重跑幂等）；只认单列表（多列数据表不碰）。找不到含关键词的框行
    抛 RuntimeError（带提示便于 harness 自纠）。
    """
    kw = _norm_ws(row_keyword)
    for t in doc.tables:
        if len(t.columns) != 1:
            continue                          # 粘贴框恒为单列；序号/报价等数据表不碰
        for row in t.rows:
            cell = row.cells[0]
            if kw not in _norm_ws(cell.text):
                continue
            if any(p._element.findall(".//" + qn("w:drawing"))
                   or p._element.findall(".//" + qn("w:pict")) for p in cell.paragraphs):
                return cell.paragraphs[-1]    # 该行已有图，幂等跳过
            p = cell.add_paragraph()
            p.alignment = 1                   # center
            p.add_run().add_picture(ensure_readable_img(img), width=Inches(width_inch))
            return p
    raise RuntimeError(f"找不到含 {row_keyword!r} 的粘贴框行；请核对框内文字（只匹配单列表格）")


# ---------------- 声明式填空清单（一次执行、批量报错，压缩 harness 轮次） ----------------

def _match_key(nk: str, alt: str | None, nhead: str) -> bool:
    """归一化后的关键词命中判断;alt 为剥掉冒号前缀的备选(「货物说明一览表：序号」→「序号」)。"""
    return nk in nhead or (alt is not None and alt in nhead)


def find_table(doc, *header_keywords: str) -> int:
    """按表头关键词定位表格（表头行含全部关键词），返回下标；找不到抛 RuntimeError。

    关键词与表头按 _norm_ws 归一化(模型常把'备\\xa0\\xa0注'回显成普通空格),
    关键词只归一化一次,不随候选表重复计算。
    """
    keys = [(_norm_ws(k), _norm_ws(k.rsplit("：", 1)[-1]) if "：" in k else None)
            for k in header_keywords]
    for i, t in enumerate(doc.tables):
        nhead = _norm_ws(" ".join(c.text for c in t.rows[0].cells))
        if all(_match_key(nk, alt, nhead) for nk, alt in keys):
            return i
    raise RuntimeError(f"找不到表头含 {header_keywords} 的表格")


def _is_fill_candidate(p) -> bool:
    """段落是否为可填点候选：空位段 / 括号占位段 / 短标签段（空白折叠后 ≤30 字含冒号）。

    地图只列候选——纯正文段 LLM 用不到，省输入 token 与注意力。
    短标签段覆盖 blank 并入 label 后的「无下划线直填」场景（如「日期：」「投标人名称：」）。
    """
    t = p.text.strip()
    if not t:
        return False
    if _has_fill_slot(p):
        return True
    if _PAREN_PLACEHOLDER.search(t):
        return True
    compact = _norm_ws(t)
    return len(compact) <= 30 and "：" in compact


def dump_fill_points(doc) -> str:
    """一次性输出模板可填点地图：段落只列可填点候选（下标/文本/是否含填空线）+ 表格表头。

    纯正文段省略（_is_fill_candidate 判定），空段落同样省略。
    """
    lines = ["== 段落 =="]
    for i, p in enumerate(doc.paragraphs):
        t = p.text.strip()
        if not t or not _is_fill_candidate(p):
            continue
        lines.append(f"[{i}]{'(线)' if _has_fill_slot(p) else ''} {t[:50]}")
    lines.append("== 表格 ==")
    for i, t in enumerate(doc.tables):
        # 表头单元格不截断:模型须逐字回显完整表头作 table_header 关键词
        head = " | ".join(c.text.strip() for c in t.rows[0].cells)
        lines.append(f"[T{i}] {head}  ({len(t.rows)}行)")
    return "\n".join(lines)


def run_fill_plan(template: str, output: str, plan: list[dict]) -> list[str]:
    """按填空清单一次性执行全部操作；单条失败不中断，返回错误清单供批量修正。

    plan 条目（op 必填）：
      {"op":"label","label":"项目名称：","value":"X"}                  # 按标签填空(段首/段中皆可,填全部命中;有无下划线均可)
      {"op":"replace","prefix":"致：","old":"（采购人）","new":"X"}      # 段内替换(全部命中同前缀段落)
      {"op":"table","table_header":["序号","名称"],"rows":[["1","X"],...]} # 按行批量填表(null 跳过该格,行不足自动加行)
      {"op":"cell","table":0,"row":1,"col":2,"value":"X"}              # 按下标填单格
      {"op":"cell","table_header":["序号","名称"],"row":1,"col":1,...} # 按表头定位填单格
      {"op":"picture","prefix":"备注：","img":"C:/...jpg","width":4.8,"caption":"附：X"}
      {"op":"append","prefix":"投标人名称：","value":"X"}               # 段末追加（无标签锚的补文字）
    """
    errors: list[str] = []
    doc = Document(template)
    # 同 prefix 连续 picture 的链式锚:每次 find_para 都回到原段会让第 2 张图插到第 1 张
    # 前面(真实 run 三证照图反序实证)——接着上一张插入位置续插,保持声明顺序。
    last_pic: tuple[str, Paragraph] | None = None
    for i, op in enumerate(plan):
        try:
            kind = op["op"]
            if kind == "label":
                n = fill_label_blank(doc, op["label"], op["value"])
                if n == 0:
                    raise RuntimeError("未命中任何带该标签的填空；请核对模板文本")
            elif kind == "replace":
                replace_in_para(doc, op["prefix"], op["old"], op["new"])
            elif kind == "table":
                t = op.get("table")
                if t is None:
                    t = find_table(doc, *op["table_header"])
                start = int(op.get("start_row", 1))
                for ri, vals in enumerate(op["rows"]):
                    for ci, v in enumerate(vals):
                        if v is None or str(v).strip() == "":
                            continue          # null/空串=跳过该格(保留原样)
                        fill_cell(doc, int(t), start + ri, ci, str(v))
            elif kind == "cell":
                t = op.get("table")
                if t is None:
                    t = find_table(doc, *op["table_header"])
                fill_cell(doc, int(t), int(op["row"]), int(op["col"]), op["value"])
            elif kind == "picture":
                prefix = op["prefix"]
                anchor = (last_pic[1] if last_pic and last_pic[0] == prefix
                          else find_para(doc, prefix))
                last_pic = (prefix, _insert_picture_after_para(
                    anchor, op["img"], float(op.get("width") or 0) or 5.6,
                    op.get("caption")))
            elif kind == "append":
                find_para(doc, op["prefix"]).add_run(op["value"])
            else:
                raise RuntimeError(f"未知 op: {kind}")
        except Exception as e:              # 收集错误继续执行，供一次修正
            head = op.get("prefix") or op.get("label") or op.get("table_header", "")
            errors.append(f"[{i}] {op.get('op')} {head}: {e}")
    doc.save(output)
    return errors
