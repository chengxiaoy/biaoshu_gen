"""标书模板填写 skill：表格填写 / 下划线填空 / 插入图片 的可复用原语。

设计要点（源自 fill 阶段 harness 实战脚本的提炼）：
- **前缀锚定**而非魔法下标：以段落文本前缀定位（如 "项目名称："），模板微调不致错位；
- **下划线填空**：值填*在下划线上*（优先填带下划线格式的空白 run；其次替换下划线字符 run
  并保留少量余线；再无则复制邻近格式插入带下划线的 run）——修复"值附加在下划线之后"的问题；
- **图片**：WEBP 伪装 .jpg 时机械转码 PNG（不读取内容）；插图带居中与可选图注。

供 fill 阶段三个 harness 节点直接 import 使用（工作区内会自动放置本文件副本）。
"""
import copy as _copy
import os

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.text.paragraph import Paragraph

UNDERLINE_CHARS = set("＿＿___―—-") - set("")  # 全角/半角下划线

# 全半角标点归一化表(一一对应单字符,归一化串下标与原文一致):LLM 回显宽度常漂移
_WIDTH_NORM = str.maketrans({"（": "(", "）": ")", "：": ":", "，": ",", "；": ";"})

# 标签之后的合法边界：分隔符/括号/空白/段末/下划线字符（防 "投标人" 误中 "投标人地址"）
_BOUNDARY_CHARS = set("：:（）() \t，、；") | UNDERLINE_CHARS


def _has_fill_slot(p: Paragraph) -> bool:
    """段落是否真实存在下划线填空位（下划线空白 run 或下划线字符 run）；无则跳过不硬插。"""
    if any(r.text and not r.text.strip() and _is_underlined(r) for r in p.runs):
        return True
    return any((r.text or "").strip() and set((r.text or "").strip()) <= UNDERLINE_CHARS
               for r in p.runs)


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
            r.text = f"{value}{'＿' * 2}"       # 值落在线上并保留余线
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


def fill_blank(doc, prefix: str, value: str) -> Paragraph:
    """在 prefix 段落的填空线上填 value（首个匹配段落）。"""
    p = find_para(doc, prefix)
    _fill_blank_in_para(p, value)
    return p


def fill_label_blank(doc, label: str, value: str) -> int:
    """段内**任意位置**按标签填其后的第一个填空（含段中部，如「编号：__ 名称：__」同段），返回填写处数。

    与 fill_all_blanks（只认段首）互补：label op 的底层原语。
    标签边界护栏同预填：标签前须是段首/分隔符/括号/空白/下划线，防前缀误中。
    """
    n = 0
    label_n = label.translate(_WIDTH_NORM)      # 模型回显宽度漂移:全半角归一化后匹配
    for p in doc.paragraphs:
        text = p.text
        text_n = text.translate(_WIDTH_NORM)    # 1:1 映射,归一化下标=原文下标
        pos = 0
        while True:
            idx = text_n.find(label_n, pos)
            if idx < 0:
                break
            pos = idx + len(label)
            if idx > 0 and text_n[idx - 1] not in _BOUNDARY_CHARS:
                continue                       # 边界不符（如「分包号」误中「包号」）
            end = idx + len(label)
            if end < len(text_n) and text_n[end] not in _BOUNDARY_CHARS:
                continue                       # 段首匹配也须验证后边界（「投标人地址」≠「投标人」）
            if _fill_blank_after(p, idx + len(label), value):
                n += 1
                text = p.text                  # 段文本已变,重找后续标签
                text_n = text.translate(_WIDTH_NORM)
                pos = idx + len(label) + len(value)
    return n


def _fill_blank_after(p: Paragraph, q: int, value: str) -> bool:
    """在段落第 q 个字符处起填空：跳过边界符（冒号/括号/空白）后须是下划线段或下划线空白 run。

    真实模板两种形态曾致漏填（run 游走须感知格式，不能纯按字符跳）：
    - 填空位本身是带下划线格式的纯空格 run——跳过循环不得越过它，遇之就地填值；
    - 下划线字符段后同一 run 还有文字（「小写：___ 大写：___」整行一个 run）——
      按正则切出纯下划线 span 填入，不要求延伸到 run 尾。
    """
    # run -> 字符区间映射
    spans = []
    start = 0
    for r in p.runs:
        t = r.text or ""
        spans.append((start, start + len(t), r))
        start += len(t)
    total = start

    def _run_at(pos: int):
        for s, e, r in spans:
            if s <= pos < e or (pos == s == e and not (r.text or "")):
                return s, e, r
        return None

    # 跳过标签后的边界符(LLM 常丢冒号:「采购代理编号」对「采购代理编号：__」);
    # 但带下划线的纯空白 run 是填空位本身,不可跳过——直接落值。
    while q < total and p.text[q] in " \t：:（）()":
        hit = _run_at(q)
        if hit is not None:
            _, _, r = hit
            if _is_underlined(r) and not (r.text or "").strip():
                r.text = value                   # 与 _fill_blank_in_para 一致:值即整线
                return True
        q += 1

    hit = _run_at(q)
    if hit is None:
        return False
    s, e, r = hit
    t = r.text or ""
    off = q - s
    import re as _re
    m = _re.match("[_＿]+", t[off:])           # 段中/至 run 尾的下划线段均可
    if m:
        r.text = t[:off] + value + "＿＿" + t[off + m.end():]
        return True
    if not t and _is_underlined(r) and q == s:  # 空 run 空位
        r.text = value
        return True
    return False


def fill_blank_before_label(doc, label: str, value: str) -> int:
    """填「空位在标签前」形态：__(标签)——下划线空位 run 后紧跟括号注记，
    且括号内容**恰为** label 单一标签（commercial 部分的主要文体，如
    「我系参加__（项目名称），采购计划编号__」）。

    多标签并列（如「（项目名称、政府采购编号、采购代理编号）」）归属不明，不填；
    括号内容须与 label 全等，防「（采购人单位名称）」误中「（单位名称）」。
    """
    import re as _re

    n = 0
    for p in doc.paragraphs:
        runs = p.runs
        for i in range(len(runs) - 1):
            r = runs[i]
            t = r.text or ""
            if not t.strip() and t and _is_underlined(r):        # 下划线空白 run
                keep = ""
            elif t.strip() and set(t.strip()) <= UNDERLINE_CHARS:  # 下划线字符段
                keep = "＿＿"
            else:
                continue
            m = _re.match(r"\s*[（(]([^（）()]+)[）)]", runs[i + 1].text or "")
            if m and m.group(1).strip() == label:
                r.text = value + keep
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


def replace_in_para(doc, prefix: str, old: str, new: str) -> Paragraph:
    """段内文本替换：只重写命中区间的 run,同段其余 run（下划线填空位等）保持不动。

    old 字面找不到时按全半角标点归一化重试（LLM 常把模板半角括号写成全角；
    映射为一一对应单字符,归一化串下标可直接映射回原文）。全部命中从右往左
    依次改写,避免下标位移。
    """
    p = find_para(doc, prefix)
    full = "".join(r.text for r in p.runs)
    matches: list[tuple[int, int]] = []
    start_at = full.find(old)
    while start_at >= 0:                                   # 字面命中(全部出现处)
        matches.append((start_at, start_at + len(old)))
        start_at = full.find(old, start_at + len(old))
    if not matches:
        nfull = full.translate(_WIDTH_NORM)
        nold = old.translate(_WIDTH_NORM)
        start_at = nfull.find(nold)
        while start_at >= 0:                               # 归一化命中
            matches.append((start_at, start_at + len(nold)))
            start_at = nfull.find(nold, start_at + len(nold))
    if not matches:
        raise RuntimeError(f"{prefix!r} 段落中未找到 {old!r}：{full[:60]!r}")

    for pos, end in reversed(matches):
        spans = []
        s0 = 0
        for r in p.runs:
            t = r.text or ""
            spans.append((s0, s0 + len(t), r))
            s0 += len(t)
        hit = [(i, s, e, r) for i, (s, e, r) in enumerate(spans) if s < end and e > pos
               or (s == e and pos <= s < end)]             # 空 run 视为在 pos 处
        if not hit:
            continue
        i0, s0_, _, r_first = hit[0]
        _, s1, _, r_last = hit[-1]
        r_first.text = (r_first.text or "")[:pos - s0_] + new \
            + (r_last.text or "") [end - s1:]
        for _, _, _, r in hit[1:]:
            r.text = ""
    return p


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


def insert_picture_after(doc, prefix: str, img: str, width_inch: float = 5.6,
                         caption: str | None = None) -> Paragraph:
    """在 prefix 段落之后插入居中图片（可选图注），返回可继续链式插入的锚段。"""
    p = find_para(doc, prefix)
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


# ---------------- 声明式填空清单（一次执行、批量报错，压缩 harness 轮次） ----------------

def _match_key(k: str, head: str) -> bool:
    """表头关键词匹配:空白/不间断空格归一化;模型常把表标题拼进关键词
    (「货物说明一览表：序号」),直接未中时剥掉冒号前缀再试。"""
    norm = lambda s: " ".join(s.replace("\xa0", " ").split())
    if norm(k) in norm(head):
        return True
    return "：" in k and norm(k.split("：")[-1]) in norm(head)


def find_table(doc, *header_keywords: str) -> int:
    """按表头关键词定位表格（表头行含全部关键词），返回下标；找不到抛 RuntimeError。"""
    for i, t in enumerate(doc.tables):
        head = " ".join(c.text for c in t.rows[0].cells)
        if all(_match_key(k, head) for k in header_keywords):
            return i
    raise RuntimeError(f"找不到表头含 {header_keywords} 的表格")


def dump_fill_points(doc) -> str:
    """一次性输出模板全部可填点地图：段落（下标/文本/是否含填空线）+ 表格（下标/表头）。"""
    lines = ["== 段落 =="]
    for i, p in enumerate(doc.paragraphs):
        t = p.text.strip()
        if not t:
            continue
        has_blank = any(r.text and not r.text.strip() and _is_underlined(r) for r in p.runs) \
            or any((r.text or "").strip() and set((r.text or "").strip()) <= UNDERLINE_CHARS
                   for r in p.runs)
        lines.append(f"[{i}]{'(线)' if has_blank else ''} {t[:50]}")
    lines.append("== 表格 ==")
    for i, t in enumerate(doc.tables):
        # 表头单元格不截断:模型须逐字回显完整表头作 table_header 关键词
        head = " | ".join(c.text.strip() for c in t.rows[0].cells)
        lines.append(f"[T{i}] {head}  ({len(t.rows)}行)")
    return "\n".join(lines)


def run_fill_plan(template: str, output: str, plan: list[dict]) -> list[str]:
    """按填空清单一次性执行全部操作；单条失败不中断，返回错误清单供批量修正。

    plan 条目（op 必填）：
      {"op":"blank","prefix":"项目名称：","value":"X"}                 # 下划线填空
      {"op":"label","label":"项目名称：","value":"X"}                  # 按标签填空(段中部亦可,填全部命中)
      {"op":"replace","prefix":"致：","old":"（采购人）","new":"X"}      # 段内替换
      {"op":"cell","table":0,"row":1,"col":2,"value":"X"}              # 按下标填格
      {"op":"cell","table_header":["序号","名称"],"row":1,"col":1,...} # 按表头定位填格
      {"op":"picture","prefix":"备注：","img":"C:/...jpg","width":4.8,"caption":"附：X"}
      {"op":"append","prefix":"投标人名称：","value":"X"}               # 段末追加（无填空线时）
    """
    errors: list[str] = []
    doc = Document(template)
    for i, op in enumerate(plan):
        try:
            kind = op["op"]
            if kind == "blank":
                fill_blank(doc, op["prefix"], op["value"])
            elif kind == "label":
                n = fill_label_blank(doc, op["label"], op["value"])
                if n == 0:
                    raise RuntimeError("未命中任何带该标签的填空；请核对模板文本")
            elif kind == "replace":
                replace_in_para(doc, op["prefix"], op["old"], op["new"])
            elif kind == "cell":
                t = op.get("table")
                if t is None:
                    t = find_table(doc, *op["table_header"])
                fill_cell(doc, int(t), int(op["row"]), int(op["col"]), op["value"])
            elif kind == "picture":
                insert_picture_after(doc, op["prefix"], op["img"],
                                     float(op.get("width", 5.6)), op.get("caption"))
            elif kind == "append":
                find_para(doc, op["prefix"]).add_run(op["value"])
            else:
                raise RuntimeError(f"未知 op: {kind}")
        except Exception as e:              # 收集错误继续执行，供一次修正
            head = op.get("prefix") or op.get("label") or op.get("table_header", "")
            errors.append(f"[{i}] {op.get('op')} {head}: {e}")
    doc.save(output)
    return errors
