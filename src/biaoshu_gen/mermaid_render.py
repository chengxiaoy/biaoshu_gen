"""mermaid 渲染校验：调 mermaid-cli（mmdc）真实解析渲染，作为结构校验之外的增量保障。

设计要点：
- 安装：`npm install -g @mermaid-js/mermaid-cli`（国内建议 npmmirror 镜像 +
  PUPPETEER_SKIP_DOWNLOAD=1 跳过 Chrome 下载，用系统 Edge/Chrome 渲染）。
- 浏览器：自动探测 Edge/Chrome 生成临时 puppeteer 配置；配置了
  mermaid_puppeteer_config 则优先使用。
- 环境缺失（mmdc 找不到/浏览器起不来）时静默跳过（返回 None）——渲染校验是
  锦上添花，不应因环境缺失把图表全部降级，结构校验仍会兜底。
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import get_settings

# stderr 命中这些关键字说明是环境问题（无浏览器/启动失败），不是语法错误
_ENV_ERRORS = ("chrome", "browser", "puppeteer", "libgbm", "display")
# mmdc 的 PATH 兜底：本会话 PATH 快照可能没有 npm 全局目录
_MMDC_FALLBACKS = (
    Path.home() / "AppData/Roaming/npm/mmdc.cmd",
    Path("/usr/local/bin/mmdc"),
    Path.home() / ".local/bin/mmdc",
)
# 系统浏览器候选（puppeteer executablePath 用）
_BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def _find_mmdc() -> str | None:
    """定位 mmdc：PATH 优先，兜底 npm 全局目录（Windows git-bash 快照 PATH 常缺）。"""
    found = shutil.which(get_settings().mermaid_cli)
    if found:
        return found
    return next((str(p) for p in _MMDC_FALLBACKS if p.exists()), None)


def _puppeteer_config() -> Path | None:
    """返回传给 mmdc -p 的 puppeteer 配置文件；无可用浏览器时 None（用其自带浏览器）。

    显式配置 mermaid_puppeteer_config 优先；否则探测 Edge/Chrome 写临时配置。
    """
    explicit = get_settings().mermaid_puppeteer_config
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    browser = next((b for b in _BROWSERS if Path(b).exists()), None)
    if browser is None:
        return None
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"executablePath": browser}, f)
    f.close()
    return Path(f.name)


def render_check(code: str) -> str | None:
    """渲染一段 mermaid 代码：语法合法返回 None，语法错误返回可作重试反馈的说明。

    环境不可用（mmdc 缺失/浏览器起不来）时返回 None 跳过校验，而非误判为图表错误。
    """
    settings = get_settings()
    if not settings.mermaid_render:
        return None
    exe = _find_mmdc()
    if exe is None:
        return None
    with tempfile.NamedTemporaryFile(
            "w", suffix=".mmd", delete=False, encoding="utf-8") as f:
        f.write(code)
        src = Path(f.name)
    out = src.with_suffix(".svg")
    cmd = [exe, "-i", str(src), "-o", str(out)]
    p_config = _puppeteer_config()
    if p_config:
        cmd += ["-p", str(p_config)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=settings.mermaid_render_timeout,
        )
    except subprocess.TimeoutExpired:
        return f"渲染超时（>{settings.mermaid_render_timeout:.0f}s），请简化图形"
    finally:
        for p in (src, out, p_config):
            if p is not None:
                p.unlink(missing_ok=True)

    stderr = (proc.stderr or "").strip()
    if proc.returncode == 0:
        return None
    lowered = stderr.lower()
    # Parse error 优先判定：其调用栈里含 puppeteer 字样，不能先被环境误判吞掉
    if "parse error" not in lowered and any(k in lowered for k in _ENV_ERRORS):
        return None    # 浏览器环境问题：跳过校验，不当作图表错误
    return _extract_error(stderr) or f"exit code {proc.returncode}"


def _extract_error(stderr: str) -> str:
    """提取 mmdc 错误的有效反馈行（Error/源码片段/Expecting），丢弃栈帧与 URL 噪声。"""
    keep: list[str] = []
    for line in stderr.splitlines():
        if line.lstrip().startswith(("at ", "at async")):
            break    # 调用栈开始处截断
        text = line.strip()
        if text and not text.startswith("Generating") and "http" not in text.lower():
            keep.append(text)
    return " | ".join(keep)[:300]
