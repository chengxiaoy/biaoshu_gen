import typer

app = typer.Typer(help="软件标书智能体 POC", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """软件标书智能体 POC（命令见后续任务）"""


def main() -> None:
    app()
