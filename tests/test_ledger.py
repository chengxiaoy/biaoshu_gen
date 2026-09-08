"""ledger 单测：企业信息记账分类、确定性读取、与 kb_v2 上传清单的分流。"""
from pathlib import Path

from biaoshu_gen.ledger import build, ragflow_files
from biaoshu_gen.utils import count_chars


def _make_company(tmp_path: Path) -> Path:
    """按真实结构构造：1、企业信息（证书图片+案例文档）/ 2、产品资料（pdf/pptx/对比表图片）。"""
    root = tmp_path / "company"
    ent = root / "1、企业信息" / "1、基础信息"
    ent.mkdir(parents=True)
    (ent / "营业执照.jpg").write_bytes(b"\xff\xd8img")
    (ent / "案例.docx").write_bytes(b"PK fake")          # ledger 只登记名字，docx 解析失败跳过
    (ent / "范围.txt").write_text("具备 ISO27001 与 ITSS。", encoding="utf-8")
    prod = root / "2、产品资料" / "硬件"
    prod.mkdir(parents=True)
    (prod / "Server介绍.pptx").write_bytes(b"PK fake")
    (prod / "白皮书.pdf").write_bytes(b"%PDF fake")
    (prod / "对比表.jpg").write_bytes(b"\xff\xd8img")
    (root / "散说明.md").write_text("根下散文件", encoding="utf-8")
    return root


def test_build_ledger_texts_only_from_company_dirs(tmp_path: Path):
    root = _make_company(tmp_path)
    ledger = build(root)
    # 企业信息区的 txt 进入记账；根下散文件与产品文档不进
    assert [n for n, _ in ledger.texts] == ["范围.txt"]
    assert "ISO27001" in ledger.texts[0][1]


def test_ledger_images_cover_whole_tree(tmp_path: Path):
    """图片是插图素材：无论企业信息区还是产品区都登记（本地磁盘路径）。"""
    ledger = build(_make_company(tmp_path))
    assert [p.name for p in ledger.images] == ["营业执照.jpg", "对比表.jpg"]


def test_ragflow_files_excludes_ledger_area(tmp_path: Path):
    """kb_v2 只收产品区文档+产品图片；企业信息区整树不上传。"""
    files = {p.name for p in ragflow_files(_make_company(tmp_path))}
    assert files == {"Server介绍.pptx", "白皮书.pdf", "对比表.jpg", "散说明.md"}


def test_ledger_missing_dir_is_empty(tmp_path: Path):
    ledger = build(tmp_path / "不存在")
    assert ledger.texts == [] and ledger.images == []
    assert ragflow_files(tmp_path / "不存在") == []


def test_dump_writes_texts_and_image_paths(tmp_path: Path):
    root = _make_company(tmp_path)
    out = build(root).dump(tmp_path / "kb.md")
    text = out.read_text(encoding="utf-8")
    assert "企业信息记账" in text and "ISO27001" in text
    assert str((root / "1、企业信息" / "1、基础信息" / "营业执照.jpg").resolve()) in text


def test_count_chars_ignores_whitespace():
    assert count_chars("a b\nc") == 3
