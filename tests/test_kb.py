from pathlib import Path

from docx import Document

from biaoshu_gen.kb import KnowledgeBase, count_chars


def _make_kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "company"
    kb.mkdir()
    (kb / "简介.md").write_text(
        "公司成立于 2010 年，专注于政务信息化，具备 CMMI5 认证。\n\n"
        "公司拥有软件测试团队，可提供驻场实施与三年质保服务。", encoding="utf-8")
    (kb / "资质.txt").write_text("具备 ISO27001 信息安全认证与 ITSS 运维认证。", encoding="utf-8")
    d = Document()
    d.add_paragraph("成功交付某省一体化政务服务平台，合同额 2000 万。")
    d.save(kb / "案例.docx")
    (kb / "营业执照.jpg").write_bytes(b"\xff\xd8fake")
    return kb


def test_load_and_search(tmp_path: Path):
    kb = KnowledgeBase.load(_make_kb_dir(tmp_path))
    hits = kb.search("信息安全 认证", top_k=2)
    assert hits and "ISO27001" in hits[0].text
    hits2 = kb.search("政务平台 交付案例", top_k=3)
    assert any("政务服务平台" in h.text for h in hits2)


def test_images_registered_not_searched(tmp_path: Path):
    kb = KnowledgeBase.load(_make_kb_dir(tmp_path))
    assert kb.image_paths() == [Path(kb.all_files()[0]).parent / "营业执照.jpg"] or \
           [p.name for p in kb.image_paths()] == ["营业执照.jpg"]
    assert all("fake" != h.text for h in kb.search("营业执照"))


def test_search_empty_kb(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert KnowledgeBase.load(empty).search("任意") == []


def test_count_chars():
    assert count_chars("你好  world\n") == 7
    assert count_chars("") == 0
