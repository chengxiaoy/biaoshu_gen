import sqlite3
from pathlib import Path

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


def _init_run(tmp_path: Path) -> None:
    t = tmp_path / "软件招标文件.docx"
    Document().save(t)
    r = runner.invoke(cli.app, ["init", "--tender", str(t), "--kb", str(tmp_path / "kb")])
    assert r.exit_code == 0, r.output


def test_init_creates_run_json_and_latest(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path)
    runs = tmp_path / "data" / "runs"
    latest = (runs / ".latest").read_text(encoding="utf-8")
    assert (runs / latest / "run.json").exists()


def test_stages_stop_and_resume(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    assert calls == ["parse_tender"]
    assert runner.invoke(cli.app, ["facts"]).exit_code == 0
    assert calls == ["parse_tender", "extract_template", "facts"]
    assert runner.invoke(cli.app, ["template"]).exit_code == 0   # 已完成 -> 不重复执行
    assert calls == ["parse_tender", "extract_template", "facts"]


def test_run_all_reaches_end(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path)
    assert runner.invoke(cli.app, ["run"]).exit_code == 0
    assert calls.count("review") >= 1 and calls[-1] in ("review", "revise")


def test_status_lists_stages(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path)
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 0 and "parse" in r.output
