from pathlib import Path

import pytest

from biaoshu_gen import harness
from biaoshu_gen.harness import HarnessError, HarnessTask, prepare_workspace, run_harness_task


def _ok_query(prompt: str, cwd: Path, max_turns: int) -> str:
    for p in Path(cwd).glob("*.md"):
        pass
    (cwd / "expected.md").write_text("done", encoding="utf-8")
    return "已产出 expected.md"


def test_prepare_workspace_copies_inputs(tmp_path: Path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1", encoding="utf-8")
    ws = prepare_workspace(tmp_path, "02_template", [(src, "input.yaml")])
    assert ws == tmp_path / "02_template"
    assert (ws / "input.yaml").read_text(encoding="utf-8") == "x: 1"


def test_run_harness_task_success(tmp_path: Path, monkeypatch):
    async def fake(prompt, cwd, max_turns):
        return _ok_query(prompt, Path(cwd), max_turns)
    monkeypatch.setattr(harness, "_query_sdk", fake)
    out = tmp_path / "expected.md"
    task = HarnessTask(prompt="做点什么", cwd=tmp_path, expected_outputs=[out])
    assert run_harness_task(task) == [out]


def test_run_harness_task_retries_once_then_raises(tmp_path: Path, monkeypatch):
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


def test_run_harness_task_retry_can_succeed(tmp_path: Path, monkeypatch):
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


def test_run_harness_task_retries_on_sdk_exception(tmp_path: Path, monkeypatch):
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
