import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from langgraph.checkpoint.sqlite import SqliteSaver
from typer.testing import CliRunner

from biaoshu_gen import cli
from biaoshu_gen import graph as g
from biaoshu_gen.state import BidState

runner = CliRunner()


def _install_fake_graph(tmp_path: Path, calls: list, monkeypatch) -> None:
    def build(node_overrides=None, checkpointer=None):
        overrides = {}
        for n in g.NODE_NAMES:
            def make(nn):
                def fn(state: BidState) -> dict:
                    calls.append(nn)
                    if nn == "body_review":
                        return {"body_review_passed": True,
                                "body_review_rounds": state.body_review_rounds + 1}
                    if nn == "review":
                        return {"review_passed": True}
                    if nn == "revise":
                        return {"revision_round": state.revision_round + 1}
                    return {}
                return fn
            overrides[n] = make(n)
        return g.build_graph(node_overrides=overrides, checkpointer=checkpointer)
    monkeypatch.setattr(cli, "build_graph", build)


class _FakeV2:
    """替身 KnowledgeBaseV2：init 的 RAGFlow 初始化不连真 server。"""

    last: "_FakeV2 | None" = None

    def __init__(self, dataset_name=None, **kw):
        self.dataset_name = dataset_name
        self._dataset = SimpleNamespace(id=f"ds-{dataset_name}")
        self.loaded: str | None = None
        _FakeV2.last = self

    def load(self, d, wait=True):
        self.loaded = [Path(p) for p in d] if isinstance(d, list) else d
        return 3


def _install_fake_v2(monkeypatch) -> None:
    import biaoshu_gen.kb_v2 as v2mod
    monkeypatch.setattr(v2mod, "KnowledgeBaseV2", _FakeV2)


def _init_run(tmp_path: Path, monkeypatch) -> None:
    _install_fake_v2(monkeypatch)
    t = tmp_path / "服务招标文件.docx"
    Document().save(t)
    r = runner.invoke(cli.app, ["init", "--tender", str(t), "--kb", str(tmp_path / "kb")])
    assert r.exit_code == 0, r.output


def test_init_ingests_ragflow_dataset(tmp_path: Path, monkeypatch):
    """init 是 RAGFlow 初始化唯一入口：dataset 按 run 命名，id 落 run.json。"""
    monkeypatch.chdir(tmp_path)
    _install_fake_v2(monkeypatch)
    t = tmp_path / "服务招标文件.docx"
    Document().save(t)
    kbdir = tmp_path / "kb"
    kbdir.mkdir()
    (kbdir / "a.md").write_text("内容", encoding="utf-8")
    r = runner.invoke(cli.app, ["init", "--tender", str(t), "--kb", str(kbdir)])
    assert r.exit_code == 0, r.output
    latest = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8")
    run = json.loads((tmp_path / "data" / "runs" / latest / "run.json").read_text(encoding="utf-8"))
    assert run["ragflow_dataset"] == "biaoshu-products"              # 本地开发固定库
    assert run["ragflow_dataset_id"] == f"ds-{run['ragflow_dataset']}"
    assert run["ragflow_docs"] == 3
    assert [p.name for p in _FakeV2.last.loaded] == ["a.md"]         # 上传清单来自 --kb 目录


def test_init_skip_ragflow_leaves_dataset_empty(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = tmp_path / "服务招标文件.docx"
    Document().save(t)
    r = runner.invoke(cli.app, ["init", "--tender", str(t), "--skip-ragflow"])
    assert r.exit_code == 0, r.output
    latest = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8")
    run = json.loads((tmp_path / "data" / "runs" / latest / "run.json").read_text(encoding="utf-8"))
    assert run["ragflow_dataset_id"] == ""                           # 检索将回退本地 BM25


def test_clean_requires_yes_and_deletes_dataset(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path, monkeypatch)
    latest = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8")

    r = runner.invoke(cli.app, ["clean", "--run-id", latest])        # 无 --yes 拒绝
    assert r.exit_code != 0

    deleted: list = []
    import biaoshu_gen.cli as cli_mod

    class _FakeRAG:
        def list_datasets(self, page=1, page_size=100):
            return [SimpleNamespace(id="ds-biaoshu-products", name="biaoshu-products")]

        def delete_datasets(self, ids):
            deleted.extend(ids)

    monkeypatch.setattr(cli_mod, "RAGFlow", lambda **kw: _FakeRAG())
    r = runner.invoke(cli.app, ["clean", "--run-id", latest, "--yes"])
    assert r.exit_code == 0, r.output
    assert deleted == ["ds-biaoshu-products"]


def test_init_creates_run_json_and_latest(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path, monkeypatch)
    runs = tmp_path / "data" / "runs"
    latest = (runs / ".latest").read_text(encoding="utf-8")
    assert (runs / latest / "run.json").exists()


def test_stages_stop_and_resume(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    assert calls == ["parse_tender"]
    assert runner.invoke(cli.app, ["facts"]).exit_code == 0
    assert calls == ["parse_tender", "extract_template", "split_template", "facts"]
    assert runner.invoke(cli.app, ["template"]).exit_code == 0   # 已完成 -> 不重复执行
    assert calls == ["parse_tender", "extract_template", "split_template", "facts"]


def test_run_all_reaches_end(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["run"]).exit_code == 0
    assert calls.count("review") >= 1 and calls[-1] in ("review", "revise")
    rid = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8")
    backs = {p.stem for p in (tmp_path / "data" / "runs" / rid / "checkpoints").glob("*.sqlite")}
    assert {"parse", "facts", "outline", "fill"} <= backs   # run 逐阶段备份,rerun 有回退锚点


def test_rerun_parse_wipes_checkpoint_and_reruns(tmp_path: Path, monkeypatch):
    """修改代码后重跑 parse：无前序 checkpoint，清空进度从头重跑（feedback #73）。"""
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    assert calls == ["parse_tender"]

    r = runner.invoke(cli.app, ["rerun", "parse"])
    assert r.exit_code == 0, r.output
    assert calls == ["parse_tender", "parse_tender"]       # 从头重跑而非拒绝


def test_rerun_parse_overwrites_output_files(tmp_path: Path, monkeypatch):
    """真 graph + 真 SqliteSaver：rerun parse 必须重写 01_parse 产物文件（feedback #73 验收）。"""
    monkeypatch.chdir(tmp_path)
    _install_fake_v2(monkeypatch)
    from biaoshu_gen.schemas import TenderMetadata

    counter = {"n": 0}

    def build(node_overrides=None, checkpointer=None):
        def parse_fn(state: BidState) -> dict:
            counter["n"] += 1
            out = Path("data") / "runs" / state.run_id / "01_parse"
            out.mkdir(parents=True, exist_ok=True)
            (out / "metadata.yaml").write_text(f"第 {counter['n']} 次解析", encoding="utf-8")
            return {"metadata": TenderMetadata(project_name=f"第{counter['n']}次")}

        overrides = {n: (parse_fn if n == "parse_tender" else (lambda s: {}))
                     for n in g.NODE_NAMES}
        return g.build_graph(node_overrides=overrides, checkpointer=checkpointer)

    monkeypatch.setattr(cli, "build_graph", build)
    _init_run(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    latest = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8")
    meta = tmp_path / "data" / "runs" / latest / "01_parse" / "metadata.yaml"
    assert meta.read_text(encoding="utf-8") == "第 1 次解析"

    r = runner.invoke(cli.app, ["rerun", "parse"])
    assert r.exit_code == 0, r.output
    assert meta.read_text(encoding="utf-8") == "第 2 次解析"      # 产物被覆盖重写


def test_rerun_facts_deletes_stage_artifact_first(tmp_path: Path, monkeypatch):
    """rerun 先删该阶段产物再重跑：facts「文件存在即跳过」不再空转。"""
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    assert runner.invoke(cli.app, ["template"]).exit_code == 0
    assert runner.invoke(cli.app, ["facts"]).exit_code == 0
    latest = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8")
    yaml_path = tmp_path / "data" / "runs" / latest / "03_facts.yaml"
    yaml_path.write_text("旧产物", encoding="utf-8")
    calls.clear()

    r = runner.invoke(cli.app, ["rerun", "facts"])
    assert r.exit_code == 0, r.output
    assert yaml_path.exists() is False                # 产物先被删除
    assert calls == ["facts"]                         # 回退到 template 后重跑 facts 节点


def test_status_lists_stages(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path, monkeypatch)
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 0 and "parse" in r.output


def test_stage_completion_backs_up_checkpoint(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    latest = (tmp_path / "data" / "runs" / ".latest").read_text(encoding="utf-8").strip()
    ck = tmp_path / "data" / "runs" / latest / "checkpoints" / "parse.sqlite"
    assert ck.exists() and ck.stat().st_size > 0


def test_main_hard_exits_on_failure_path(monkeypatch):
    """失败路径(typer Exit -> SystemExit)也须硬退出:Windows 上未关闭的 asyncio
    IOCP 循环挂死解释器关停——成功路径已有 os._exit,失败路径曾漏,实测失败后
    进程挂 ~5 分钟才吐 Proactor WinError 6(run-20260908-215413)。"""
    import contextlib
    import os as _os
    import sys as _sys

    exits = []
    monkeypatch.setattr(_os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(cli, "app", lambda: (_ for _ in ()).throw(SystemExit(1)))

    with contextlib.suppress(SystemExit):      # 非 Windows 走正常 raise
        cli.main()
    assert exits == ([1] if _sys.platform == "win32" else [])
