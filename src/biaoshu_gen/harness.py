"""Claude Code SDK（claude-agent-sdk）封装：文件操作型 harness 节点统一入口。

SDK 以子进程方式拉起 claude CLI，自动继承本机环境
（ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN -> 智谱网关）。
"""
import asyncio
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_settings


class HarnessError(RuntimeError):
    pass


@dataclass
class HarnessTask:
    prompt: str
    cwd: Path
    expected_outputs: list[Path]
    max_turns: int = 0            # 0 -> 使用 settings.harness_max_turns


async def _query_sdk(prompt: str, cwd: Path, max_turns: int) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(
        cwd=str(cwd),
        max_turns=max_turns,
        permission_mode="bypassPermissions",   # POC 本机受控工作区
    )
    final = ""
    async for msg in query(prompt=prompt, options=options):
        if getattr(msg, "type", "") == "result":
            final = getattr(msg, "result", "") or ""
    return final


def _missing_outputs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists() or p.stat().st_size == 0]


def _run_sdk(prompt: str, cwd: Path, max_turns: int) -> str:
    """asyncio.run 包装；网关偶发 error result 时抛出（上层重试）。"""
    return asyncio.run(_query_sdk(prompt, cwd, max_turns))


def run_harness_task(task: HarnessTask) -> list[Path]:
    """执行任务；SDK 异常或产物缺失 -> 带反馈重试一次 -> 仍失败则抛 HarnessError。"""
    max_turns = task.max_turns or get_settings().harness_max_turns
    first = ""
    try:
        first = _run_sdk(task.prompt, task.cwd, max_turns)
    except Exception as e:                    # 网关/子进程偶发失败，重试一次
        print(f"⚠ harness SDK 首次调用失败（{e}），重试一次…", file=sys.stderr)
        first = _run_sdk(task.prompt, task.cwd, max_turns)
    missing = _missing_outputs(task.expected_outputs)
    if missing:
        retry = (
            task.prompt
            + "\n\n【重试提示】上次运行未产出以下文件，请务必产出：\n"
            + "\n".join(str(p) for p in missing)
            + f"\n\n上次运行最终输出（截断）：\n{first[-2000:]}"
        )
        asyncio.run(_query_sdk(retry, task.cwd, max_turns))
        missing = _missing_outputs(task.expected_outputs)
    if missing:
        raise HarnessError("harness 未产出: " + ", ".join(str(p) for p in missing))
    return list(task.expected_outputs)


def prepare_workspace(run_dir: Path, stage_subdir: str,
                      inputs: list[tuple[Path, str]] | None = None) -> Path:
    ws = run_dir / stage_subdir
    ws.mkdir(parents=True, exist_ok=True)
    for src, name in inputs or []:
        target = ws / name
        if not target.exists():
            shutil.copyfile(src, target)
    return ws


def prepare_agent_workspace(state, subdir: str,
                            extra_inputs: list[tuple[Path, Path | str]] | None = None) -> Path:
    """填充/审核类 harness 节点的标准工作区：
    基础输入 tender.md + invalidation.yaml + 可选 标书模板.docx，附加调用方输入，并生成 kb.md。"""
    from .kb import KnowledgeBase
    from .state import run_dir

    parse = run_dir(state) / "01_parse"
    inputs = [(parse / "tender.md", "tender.md"),
              (parse / "invalidation.yaml", "invalidation.yaml")]
    if state.template_docx_path:
        inputs.append((Path(state.template_docx_path), "标书模板.docx"))
    inputs.extend([(Path(p), n) for p, n in (extra_inputs or [])])
    ws = prepare_workspace(run_dir(state), subdir, inputs)
    KnowledgeBase.load(Path(state.kb_dir)).dump_summary(ws / "kb.md")
    return ws
