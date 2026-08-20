"""typer CLI：分阶段子命令 = 恢复 checkpoint 跑到对应阶段后停。"""
import json
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path

import typer
from langgraph.checkpoint.sqlite import SqliteSaver

from .config import get_settings
from .graph import STAGES, STAGE_ORDER, build_graph

app = typer.Typer(help="软件标书智能体 POC", no_args_is_help=True)

INIT_FIELDS = ("run_id", "tender_path", "kb_dir", "template_docx_path")

_STAGE_INDEX = {s: i for i, s in enumerate(STAGE_ORDER)}
_NODE_STAGE = {n: i for i, s in enumerate(STAGE_ORDER) for n in STAGES[s].members}


def runs_root() -> Path:
    return get_settings().data_dir / "runs"


def _resolve_run_id(run_id: str | None) -> str:
    if run_id:
        return run_id
    latest = runs_root() / ".latest"
    if latest.exists():
        return latest.read_text(encoding="utf-8").strip()
    ids = sorted(p.name for p in runs_root().iterdir() if p.is_dir()) if runs_root().exists() else []
    if not ids:
        raise typer.BadParameter("没有可用 run，请先执行 biaoshu init")
    return ids[-1]


def _load_run(run_id: str) -> dict:
    run_json = runs_root() / run_id / "run.json"
    if not run_json.exists():
        raise typer.BadParameter(f"run 不存在: {run_json}")
    return json.loads(run_json.read_text(encoding="utf-8"))


def _build_graph_for_run(run_dir: Path):
    conn = sqlite3.connect(run_dir / "checkpoint.sqlite", check_same_thread=False)
    return build_graph(checkpointer=SqliteSaver(conn))


def _beyond_stage(next_nodes, stage: str) -> bool:
    """pending 节点是否全部位于 stage 之后（即本阶段已完成，无需执行）。"""
    return all(_NODE_STAGE[n] > _STAGE_INDEX[stage] for n in next_nodes)


def execute_stage(graph, run_id: str, stage: str | None, initial_input: dict | None) -> None:
    """恢复 checkpoint 跑到指定阶段；stage 为 None 或 'revise' 时跑到 END。"""
    config = {"configurable": {"thread_id": run_id}}
    # langgraph 0.6.11：interrupt_after 是 invoke 的关键字参数（写进 config dict 会被忽略）
    stop_nodes = list(STAGES[stage].end_nodes) if stage and stage != "revise" else None
    snap = graph.get_state(config)
    if not snap.values:
        graph.invoke(initial_input, config, interrupt_after=stop_nodes)
    else:
        if stop_nodes is not None and _beyond_stage(snap.next, stage):
            return                                      # 本阶段已完成，不重复执行
        graph.invoke(None, config, interrupt_after=stop_nodes)
    while True:
        snap = graph.get_state(config)
        if not snap.next:                                   # 已到 END
            break
        if stop_nodes is not None and not (set(snap.next) & set(STAGES[stage].members)):
            break                                           # 下一工作已越出本阶段
        graph.invoke(None, config, interrupt_after=stop_nodes)


def _sqlite_backup(src_path: Path, dst_path: Path) -> None:
    """sqlite 安全复制（backup API 处理 WAL；目标存在则覆盖）。"""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def _backup_checkpoint(run_dir: Path, stage: str) -> None:
    """阶段完成后备份 checkpoint 到 checkpoints/<stage>.sqlite（支持选择性重跑）。

    注意：备份后不能删 WAL——graph 连接可能仍持有该文件（Windows 文件锁）。
    """
    ck_dir = run_dir / "checkpoints"
    ck_dir.mkdir(parents=True, exist_ok=True)
    _sqlite_backup(run_dir / "checkpoint.sqlite", ck_dir / f"{stage}.sqlite")


def _restore_checkpoint(run_dir: Path, stage: str) -> None:
    """把 checkpoints/<stage>.sqlite（该阶段完成时的状态）恢复为当前 checkpoint。"""
    ck = run_dir / "checkpoints" / f"{stage}.sqlite"
    if not ck.exists():
        raise typer.BadParameter(f"没有 {stage} 阶段的 checkpoint 备份（{ck}）")
    _sqlite_backup(ck, run_dir / "checkpoint.sqlite")
    _drop_wal(run_dir)


def _drop_wal(run_dir: Path) -> None:
    """清除可能残留的 WAL/SHM 文件，避免旧事务污染恢复后的数据库。"""
    for suffix in ("-wal", "-shm"):
        p = run_dir / f"checkpoint.sqlite{suffix}"
        if p.exists():
            p.unlink()


def _run_stage(stage: str | None, run_id_opt: str | None) -> None:
    rid = _resolve_run_id(run_id_opt)
    run = _load_run(rid)
    graph = _build_graph_for_run(runs_root() / rid)
    snap = graph.get_state({"configurable": {"thread_id": rid}})
    initial = {k: run[k] for k in INIT_FIELDS if run.get(k)} if not snap.values else None
    try:
        execute_stage(graph, rid, stage, initial)
    except Exception as e:
        err = runs_root() / rid / "error.log"
        err.parent.mkdir(parents=True, exist_ok=True)
        err.write_text(f"{e}\n\n{traceback.format_exc()}", encoding="utf-8")
        typer.secho(f"阶段执行失败，详情见 {err}", fg=typer.colors.RED)
        raise typer.Exit(1)
    if stage is not None:                              # 阶段成功 -> 备份 checkpoint
        _backup_checkpoint(runs_root() / rid, stage)
    typer.secho(f"完成: {stage or '全部流程'}", fg=typer.colors.GREEN)


@app.command()
def rerun(
    stage: str = typer.Argument(..., help="要重跑的阶段（回退到其前一个阶段的 checkpoint 备份）"),
    run_id: str = typer.Option(None, "--run-id"),
) -> None:
    """回退到该阶段开始前的 checkpoint 并重跑（选择性重跑）。"""
    if stage not in STAGE_ORDER:
        raise typer.BadParameter(f"未知阶段 {stage}，可选: {', '.join(STAGE_ORDER)}")
    idx = STAGE_ORDER.index(stage)
    prev = STAGE_ORDER[idx - 1] if idx > 0 else None
    rid = _resolve_run_id(run_id)
    run_dir = runs_root() / rid
    if prev is None:
        raise typer.BadParameter("parse 是首个阶段，没有可回退的 checkpoint（如需重跑请删除 run 重新 init）")
    _restore_checkpoint(run_dir, prev)
    typer.secho(f"已回退到 {prev} 完成时的状态，开始重跑 {stage}…", fg=typer.colors.YELLOW)
    _run_stage(stage, rid)


@app.command()
def init(
    tender: Path = typer.Option(..., exists=True, dir_okay=False, help="招标文件 docx"),
    kb: Path = typer.Option(Path("data/company"), help="企业信息知识库目录"),
    run_id: str = typer.Option(None, help="run 标识，缺省按时间生成"),
) -> None:
    """创建 run 目录与 run.json。"""
    rid = run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run_dir = runs_root() / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    template = next(
        (p for p in sorted(tender.parent.glob("*.docx"))
         if "模板" in p.stem and p.resolve() != tender.resolve()), None)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid,
        "tender_path": str(tender.resolve()),
        "kb_dir": str(kb.resolve()),
        "template_docx_path": str(template.resolve()) if template else "",
        "created_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (runs_root() / ".latest").parent.mkdir(parents=True, exist_ok=True)
    (runs_root() / ".latest").write_text(rid, encoding="utf-8")
    typer.secho(f"run 已创建: {run_dir}", fg=typer.colors.GREEN)
    if template:
        typer.echo(f"自动发现响应模板: {template}")


def _make_stage_command(stage: str):
    def cmd(run_id: str | None = typer.Option(None, "--run-id")) -> None:
        _run_stage(stage, run_id)
    cmd.__name__ = stage
    cmd.__doc__ = f"执行并停在 {stage} 阶段之后。"
    return cmd


for _stage in STAGE_ORDER:
    app.command(_stage)(_make_stage_command(_stage))


@app.command()
def run(run_id: str | None = typer.Option(None, "--run-id")) -> None:
    """全自动执行全部流程（端到端冒烟）。"""
    _run_stage(None, run_id)


@app.command()
def status(run_id: str | None = typer.Option(None, "--run-id")) -> None:
    """查看 run 进度与产物清单。"""
    rid = _resolve_run_id(run_id)
    run = _load_run(rid)
    run_dir = runs_root() / rid
    typer.echo(f"run: {rid}")
    typer.echo(f"招标文件: {run.get('tender_path')}")
    typer.echo(f"知识库: {run.get('kb_dir')}")
    for name, path in [
        ("parse", run_dir / "01_parse" / "metadata.yaml"),
        ("template", run_dir / "02_template" / "template.md"),
        ("facts", run_dir / "03_facts.yaml"),
        ("outline", run_dir / "04_outline.yaml"),
        ("body", run_dir / "05_body" / "body.md"),
        ("fill", run_dir / "06_fill" / "forms" / "forms.docx"),
        ("assemble", run_dir / "07_draft" / "latest.txt"),
        ("review", run_dir / "08_review" / "review_round_1.md"),
    ]:
        mark = "[x]" if path.exists() else "[ ]"
        typer.echo(f"  {mark} {name}: {path}")


def main() -> None:
    app()
