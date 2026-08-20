"""Claude Code SDK（claude-agent-sdk）封装：文件操作型 harness 节点统一入口。

SDK 以子进程方式拉起 claude CLI，自动继承本机环境
（ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN -> 智谱网关）。
"""
import asyncio
import shutil
import sys
import time
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


def _find_run_dir(cwd: Path) -> Path | None:
    """从工作区向上找 run 根目录（含 run.json），用于落 harness 调试日志。"""
    p = cwd
    while p != p.parent:
        if (p / "run.json").exists():
            return p
        p = p.parent
    return None


def _debug_file_for(run_dir: Path, cwd: Path) -> str:
    """各 harness 节点独立调试日志：run/harness_debug/<工作区相对路径>.log。

    必须返回**绝对路径**：CLI 子进程 cwd 是工作区，相对路径会解析到错误位置导致日志不落盘。
    """
    run_dir = run_dir.resolve()
    try:
        rel = cwd.resolve().relative_to(run_dir)
        stem = "_".join(rel.parts) if rel.parts else "root"
    except ValueError:
        stem = cwd.name or "root"
    d = run_dir / "harness_debug"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{stem}.log")


async def _query_sdk(prompt: str, cwd: Path, max_turns: int) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, query

    s = get_settings()
    # harness 节点可用独立模型（HARNESS_MODEL），缺省跟随 llm_model。
    model = s.harness_model or s.llm_model
    # claude agent 调试日志：各节点独立文件（run/harness_debug/<工作区>.log，绝对路径）
    extra_args: dict = {}
    run_dir = _find_run_dir(cwd)
    transcript: Path | None = None
    if run_dir is not None:
        extra_args["debug-file"] = _debug_file_for(run_dir, cwd)
        transcript = run_dir / "harness_debug" / (cwd.resolve().name + ".transcript.log")
    options = ClaudeAgentOptions(
        cwd=str(cwd),
        max_turns=max_turns,
        permission_mode="bypassPermissions",   # POC 本机受控工作区
        model=model,
        setting_sources=[],                    # 跳过用户/项目 settings（其 ANTHROPIC_* 会覆盖注入配置）
        extra_args=extra_args,
        # 全面使用 .env 配置（BASE_URL/API_KEY/MODEL_NAME），覆盖本机继承的 ANTHROPIC_* 环境变量。
        env={
            "ANTHROPIC_BASE_URL": s.anthropic_base_url,
            "ANTHROPIC_AUTH_TOKEN": s.llm_api_key,
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        },
    )
    final = ""
    async for msg in query(prompt=prompt, options=options):
        if transcript is not None:
            _log_msg(transcript, msg)
        # claude-agent-sdk 0.2.x 的 ResultMessage 无 .type 字段（type 为 None），
        # 以 dataclass 属性判断：只有 ResultMessage 带 .result 文本
        if hasattr(msg, "result") and isinstance(getattr(msg, "result", None), str):
            final = msg.result or ""
    return final


def _log_msg(transcript: Path, msg) -> None:
    """把 agent 每一步（assistant 文本/思考、tool 调用与入参、tool 结果）追加到 transcript 日志。

    claude-agent-sdk 0.2.x yield 的是扁平 dataclass（没有 .message 字段）：
    AssistantMessage.content 为 TextBlock/ThinkingBlock/ToolUseBlock 对象列表，
    tool 结果挂在 UserMessage.content 的 ToolResultBlock 里，ResultMessage 为汇总。
    """
    import json as _json
    from datetime import datetime, timezone

    from claude_agent_sdk import (
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
    )

    ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    lines: list[str] = []
    if isinstance(msg, AssistantMessage):
        for part in msg.content or []:
            if isinstance(part, TextBlock):
                lines.append(f"A {(part.text or '')[:400]}")
            elif isinstance(part, ThinkingBlock):
                lines.append(f"T {(part.thinking or '')[:200]}")
            elif isinstance(part, ToolUseBlock):
                lines.append(f"TOOL {part.name} "
                             f"{_json.dumps(part.input, ensure_ascii=False, default=str)[:600]}")
    elif isinstance(msg, UserMessage):
        for part in (msg.content if isinstance(msg.content, list) else []):
            if isinstance(part, ToolResultBlock):
                c = part.content
                if isinstance(c, list):
                    c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
                mark = "!" if part.is_error else ""
                lines.append(f"RESULT{mark} {part.tool_use_id} {str(c)[:300]}")
    elif isinstance(msg, ResultMessage):
        head = (f"SUMMARY subtype={msg.subtype} is_error={msg.is_error} "
                f"turns={msg.num_turns} {msg.duration_ms}ms")
        if msg.errors:
            head += f" errors={'; '.join(msg.errors)[:200]}"
        lines.append(head)
        if msg.result:
            lines.append(f"FINAL {msg.result[:400]}")
    if not lines:
        return
    transcript.parent.mkdir(parents=True, exist_ok=True)
    with transcript.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {type(msg).__name__}\n" + "\n".join(lines) + "\n")


def _missing_outputs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists() or p.stat().st_size == 0]


def _run_sdk(prompt: str, cwd: Path, max_turns: int) -> str:
    """asyncio.run 包装；网关偶发 error result 时抛出（上层重试）。"""
    return asyncio.run(_query_sdk(prompt, cwd, max_turns))


_SDK_RETRIES = 3          # SDK 异常（网关/子进程偶发 error result）重试次数


def run_harness_task(task: HarnessTask) -> list[Path]:
    """执行任务；SDK 异常重试（≤3 次退避）；产物缺失再带反馈重试一次 -> 仍失败抛 HarnessError。"""
    max_turns = task.max_turns or get_settings().harness_max_turns
    first = ""
    for attempt in range(_SDK_RETRIES):
        try:
            first = _run_sdk(task.prompt, task.cwd, max_turns)
            break
        except Exception as e:                # 网关/子进程偶发 error result
            if attempt == _SDK_RETRIES - 1:
                raise
            print(f"⚠ harness SDK 调用失败（{e}），{attempt + 1}/{_SDK_RETRIES} 次后重试…",
                  file=sys.stderr)
            time.sleep(15 * (attempt + 1))
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
        # 输入必须**总是覆盖**为当前状态：曾因"已存在则跳过"把过期 review_report.md
        # 留在工作区，agent 拿旧报告改新稿，白烧几分钟核对草稿结构。
        shutil.copyfile(src, ws / name)
    return ws


def prepare_agent_workspace(state, subdir: str,
                            extra_inputs: list[tuple[Path, Path | str]] | None = None) -> Path:
    """填充/审核类 harness 节点的标准工作区：
    基础输入 tender.md + invalidation.yaml + 可选 标书模板.docx，附加调用方输入，生成 kb.md，
    并投放 fill_skill.py（表格填写/下划线填空/插图原语，供 harness 直接 import）。"""
    from .kb import KnowledgeBase
    from .state import run_dir

    parse = run_dir(state) / "01_parse"
    inputs = [(parse / "tender.md", "tender.md"),
              (parse / "invalidation.yaml", "invalidation.yaml")]
    if state.template_docx_path:
        inputs.append((Path(state.template_docx_path), "标书模板.docx"))
    inputs.extend([(Path(p), n) for p, n in (extra_inputs or [])])
    ws = prepare_workspace(run_dir(state), subdir, inputs)
    skill_src = Path(__file__).with_name("fill_skill.py")
    if skill_src.exists():
        shutil.copyfile(skill_src, ws / "fill_skill.py")   # 总是同步最新 skill
    KnowledgeBase.load(Path(state.kb_dir)).dump_summary(ws / "kb.md")
    return ws


def environment_notes() -> str:
    """给 harness prompt 的环境说明：cwd/解释器写死，省掉 agent 自探的 turns。"""
    return (
        "环境说明（已核实，直接采信）：\n"
        "- 当前工作目录已经是工作区，文件一律用相对路径访问，不要 cd 到别处\n"
        f"- Python 解释器用绝对路径：{sys.executable}（PATH 里可能没有 python 命令）\n"
        "- fill_skill.py 已在工作区内，可直接 import"
    )
