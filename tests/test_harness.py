from pathlib import Path

import pytest

from biaoshu_gen import harness
from biaoshu_gen.harness import HarnessError, HarnessTask, prepare_workspace, run_harness_task


def _ok_query(prompt: str, cwd: Path, max_turns: int) -> str:
    for p in Path(cwd).glob("*.md"):
        pass
    (cwd / "expected.md").write_text("done", encoding="utf-8")
    return "已产出 expected.md"


@pytest.fixture
def harness_settings(monkeypatch):
    """注入合法 harness 三件套（run_harness_task 入口校验需要），不依赖本机 .env。"""
    from biaoshu_gen.config import Settings
    fake = Settings(
        _env_file=None,
        harness_api_key="sk-test-harness",
        harness_base_url="https://gw.example.com/anthropic",
        harness_model="test-model",
    )
    monkeypatch.setattr(harness, "get_settings", lambda: fake)


def test_prepare_workspace_copies_inputs(tmp_path: Path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1", encoding="utf-8")
    ws = prepare_workspace(tmp_path, "02_template", [(src, "input.yaml")])
    assert ws == tmp_path / "02_template"
    assert (ws / "input.yaml").read_text(encoding="utf-8") == "x: 1"


def test_prepare_workspace_overwrites_stale_input(tmp_path: Path):
    """输入必须覆盖为当前状态——曾因'已存在则跳过'把过期 review_report.md 留在工作区。"""
    src = tmp_path / "report.md"
    src.write_text("新报告", encoding="utf-8")
    ws = prepare_workspace(tmp_path, "07_draft", [(src, "review_report.md")])
    src.write_text("更新后的报告", encoding="utf-8")            # 源文件更新
    prepare_workspace(tmp_path, "07_draft", [(src, "review_report.md")])
    assert (ws / "review_report.md").read_text(encoding="utf-8") == "更新后的报告"


def test_prepare_workspace_skips_self_copy(tmp_path: Path):
    """源文件已在工作区内（revise 的草稿 v1 就在 07_draft）：跳过而非 SameFileError。"""
    ws = prepare_workspace(tmp_path, "07_draft")
    draft = ws / "标书草稿_v1.docx"
    draft.write_bytes(b"docx")
    prepare_workspace(tmp_path, "07_draft", [(draft, draft.name)])     # 不抛异常
    assert draft.read_bytes() == b"docx"


def test_environment_notes_mentions_interpreter():
    from biaoshu_gen.harness import environment_notes
    notes = environment_notes()
    import sys
    assert sys.executable in notes
    assert "相对路径" in notes and "fill_skill" in notes


def test_run_harness_task_success(tmp_path: Path, harness_settings, monkeypatch):
    async def fake(prompt, cwd, max_turns):
        return _ok_query(prompt, Path(cwd), max_turns)
    monkeypatch.setattr(harness, "_query_sdk", fake)
    out = tmp_path / "expected.md"
    task = HarnessTask(prompt="做点什么", cwd=tmp_path, expected_outputs=[out])
    assert run_harness_task(task) == [out]


def test_run_harness_task_retries_once_then_raises(tmp_path: Path, harness_settings, monkeypatch):
    calls = []

    async def fake(prompt, cwd, max_turns):
        calls.append(prompt)
        return "什么都没做"
    monkeypatch.setattr(harness, "_query_sdk", fake)
    task = HarnessTask(prompt="做点什么", cwd=tmp_path, expected_outputs=[tmp_path / "expected.md"])
    with pytest.raises(HarnessError) as e:
        run_harness_task(task)
    assert len(calls) == 2                    # 原始 + 重试一次
    assert "expected.md" in str(e.value)
    assert "未产出" in calls[1]               # 重试 prompt 带缺项反馈


def test_run_harness_task_retry_can_succeed(tmp_path: Path, harness_settings, monkeypatch):
    n = 0

    async def fake(prompt, cwd, max_turns):
        nonlocal n
        n += 1
        if n == 2:
            (Path(cwd) / "expected.md").write_text("ok", encoding="utf-8")
        return "r"
    monkeypatch.setattr(harness, "_query_sdk", fake)
    assert run_harness_task(HarnessTask(prompt="p", cwd=tmp_path,
                                        expected_outputs=[tmp_path / "expected.md"]))


def test_run_harness_task_retries_on_sdk_exception(tmp_path: Path, harness_settings, monkeypatch):
    """SDK 首次调用异常（网关偶发）-> 重试一次成功。"""
    calls = []

    async def flaky(prompt, cwd, max_turns):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("Claude Code returned an error result")
        (Path(cwd) / "expected.md").write_text("ok", encoding="utf-8")
        return "done"

    monkeypatch.setattr(harness, "_query_sdk", flaky)
    out = tmp_path / "expected.md"
    assert run_harness_task(HarnessTask(prompt="p", cwd=tmp_path, expected_outputs=[out])) == [out]
    assert len(calls) == 2


def test_find_run_dir():
    from biaoshu_gen.harness import _find_run_dir
    from pathlib import Path
    p = Path("data/runs/x/06_fill/forms")
    assert _find_run_dir(p) is None                 # 未落盘时不返回


def test_run_harness_task_requires_harness_settings(tmp_path: Path, monkeypatch):
    """三件套缺失 -> 立即抛 HarnessError，不触发 SDK 调用（重试循环之前）。"""
    from biaoshu_gen.config import Settings
    monkeypatch.setattr(harness, "get_settings",
                        lambda: Settings(_env_file=None))          # 三件套全空

    async def must_not_run(prompt, cwd, max_turns):
        raise AssertionError("SDK 不应被调用")

    monkeypatch.setattr(harness, "_query_sdk", must_not_run)
    task = HarnessTask(prompt="p", cwd=tmp_path, expected_outputs=[tmp_path / "expected.md"])
    with pytest.raises(HarnessError) as e:
        run_harness_task(task)
    assert "HARNESS_API_KEY" in str(e.value)
    assert "HARNESS_BASE_URL" in str(e.value)
    assert "HARNESS_MODEL" in str(e.value)


def test_run_harness_task_error_names_only_missing_vars(tmp_path: Path, monkeypatch):
    from biaoshu_gen.config import Settings
    monkeypatch.setattr(harness, "get_settings",
                        lambda: Settings(_env_file=None, harness_api_key="sk-x"))

    async def must_not_run(prompt, cwd, max_turns):
        raise AssertionError("SDK 不应被调用")

    monkeypatch.setattr(harness, "_query_sdk", must_not_run)
    task = HarnessTask(prompt="p", cwd=tmp_path, expected_outputs=[tmp_path / "expected.md"])
    with pytest.raises(HarnessError) as e:
        run_harness_task(task)
    assert "HARNESS_API_KEY" not in str(e.value)      # 已配置的不点名
    assert "HARNESS_BASE_URL" in str(e.value)


def test_query_sdk_injects_harness_env(harness_settings, tmp_path: Path, monkeypatch):
    """env 注入来自 harness 三件套：不派生、不复用 llm key、不回退 llm 模型。"""
    import claude_agent_sdk as cas
    captured = {}

    async def fake_query(*, prompt, options):
        captured["env"] = dict(options.env)
        captured["model"] = options.model
        return
        yield                                  # 使其成为 async generator

    monkeypatch.setattr(cas, "query", fake_query)
    import asyncio
    asyncio.run(harness._query_sdk("提示", tmp_path, 3))
    assert captured["model"] == "test-model"
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://gw.example.com/anthropic"
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-test-harness"
    assert captured["env"]["ANTHROPIC_MODEL"] == "test-model"
