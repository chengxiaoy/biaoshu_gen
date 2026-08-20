"""节点 12：按审核意见修改草稿（harness），版本号管理。

提速三件套（源自 2026-08-20 transcript 逐轨迹分析）：
- P0 输入总是覆盖投放（prepare_workspace）：过期 review_report.md 留在工作区，
  agent 会拿旧地图改新稿，白烧几分钟核对草稿结构；
- P1 环境说明预注入（environment_notes）：cwd/python 解释器绝对路径写进 prompt，
  省掉自探工作目录与找解释器的 turns；
- P2 草稿地图宿主侧生成（_map.txt 文件投放）：agent 按需 grep/局部读。
  注意区别于早期把 13K 地图整段注入 prompt 的方案（每轮 LLM 调用重复携带，实测拖慢，已回退）。
仍只预注入小体积材料（facts/invalidation/scoring）。
"""
import sys
from pathlib import Path

from ..harness import HarnessTask, environment_notes, prepare_agent_workspace, run_harness_task
from ..prompts.revise import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def _inject(state: BidState) -> str:
    d = run_dir(state)

    def _read(*rel: str) -> str:
        p = d.joinpath(*rel)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    parts = [
        "【facts.yaml 全文】\n" + _read("03_facts.yaml"),
        "【废标项+扣分项】\n" + _read("01_parse", "invalidation.yaml"),
        "【评分标准】\n" + _read("01_parse", "scoring.yaml"),
    ]
    return "\n\n".join(p for p in parts if p)


def _write_draft_map(ws: Path, draft: Path) -> Path | None:
    """宿主侧生成草稿结构地图（零 turns）；失败不阻塞，agent 可自行 dump。"""
    try:
        import docx

        from ..fill_skill import dump_fill_points
        path = ws / "_map.txt"
        path.write_text(dump_fill_points(docx.Document(str(draft))), encoding="utf-8")
        return path
    except Exception as e:
        print(f"⚠ 草稿地图生成失败（{e}），agent 可自行 dump", file=sys.stderr)
        return None


def revise_node(state: BidState) -> dict:
    d = run_dir(state)
    n = state.draft_version + 1
    ws = prepare_agent_workspace(state, "07_draft", [
        (Path(state.draft_docx_path), Path(state.draft_docx_path).name),
        (Path(state.review_report_path), "review_report.md"),
        (d / "03_facts.yaml", "facts.yaml"),
    ])
    _write_draft_map(ws, Path(state.draft_docx_path))
    out = ws / f"标书草稿_v{n}.docx"
    run_harness_task(HarnessTask(
        prompt=(SYSTEM + "\n\n" + build_user_prompt(
            str(out), n, current=Path(state.draft_docx_path).name,
            env=environment_notes())
            + "\n\n" + _inject(state)),
        cwd=ws, expected_outputs=[out]))
    (ws / "latest.txt").write_text(str(n), encoding="utf-8")
    updates: dict = {
        "draft_docx_path": str(out),
        "draft_version": n,
        "revision_round": state.revision_round + 1,
    }
    md_out = ws / f"标书草稿_v{n}.md"
    if md_out.exists():
        updates["draft_md_path"] = str(md_out)
    return updates
