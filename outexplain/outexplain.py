# Standard library
import os
import sys
import argparse
import platform
import subprocess
from typing import Literal, Optional, List
from pathlib import Path

# Third party
from rich.console import Console

# Local
from outexplain.storage import append_history, read_history
from outexplain.utils import (
    Command,
    MAX_COMMANDS_DEFAULT,
    MAX_HISTORY_LINES,
    Shell,
    build_context_from_commands,
    choose_symbols,
    detect_terminal_info,
    explain,
    format_terminal_info,
    get_commands,
    get_shell,
    get_terminal_context,
    truncate_commands,
)


# ---------------------------
# Console color system helper
# ---------------------------
def _color_system_from_depth(depth: int) -> Literal["auto", "standard", "256", "truecolor", "windows"]:
    if depth >= 24:
        return "truecolor"
    if depth >= 256:
        return "256"
    if platform.system() == "Windows":
        return "windows"
    return "standard"


def _read_last_commands_from_ps_history(max_count: int) -> List[Command]:
    appdata = os.getenv("APPDATA", "")
    paths = [
        Path(appdata) / "Microsoft" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt",
        Path(appdata) / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt",
        ]
    existing = [p for p in paths if p.exists()]
    if not existing:
        return []
    path = max(existing, key=lambda p: p.stat().st_mtime)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    commands: List[str] = [ln.strip() for ln in lines if
            ln.strip() and not ln.lower().startswith(("outexplain", "python -m outexplain"))][-max_count:]
    return [Command(text=c, output="") for c in commands]


def _read_commands_from_ps_transcript(max_count: int) -> List[Command]:
    docs = Path.home() / "Documents"
    candidates = sorted(docs.glob("PowerShell_transcript*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        slice_text = "\n".join(text.splitlines()[-MAX_HISTORY_LINES:])
        shell = Shell(path=str(path), name="powershell", prompt=">")
        commands = get_commands(slice_text, shell, max_commands=max_count)
        if commands:
            return commands
    return []


def _clean_history_line(line: str) -> Optional[str]:
    line = line.strip()
    if not line:
        return None
    if line.lower().startswith(("outexplain", "python -m outexplain")):
        return None
    if line.startswith(":") and ";" in line:
        # zsh style timestamped history
        line = line.split(";", 1)[1].strip()
    if line and line[0].isdigit() and " " in line:
        # history output like " 203  ls"
        line = line.split(" ", 1)[1].strip()
    return line or None


def _has_missing_output(commands: List[Command]) -> bool:
    return any(not (cmd.output or "").strip() for cmd in commands)


# ---------------------------
# Bash / Git Bash / Zsh helpers
# ---------------------------
def _read_bashlike_history(shell_path: Optional[str], max_count: int) -> List[Command]:
    exe = shell_path or "bash"
    commands: List[str] = []

    try:
        proc = subprocess.run([exe, "-lc", f"fc -ln -n -{max_count}"],
                              text=True, capture_output=True, cwd=os.getcwd())
        if proc.stdout:
            cleaned = [_clean_history_line(ln) for ln in proc.stdout.splitlines()]
            commands = [ln for ln in cleaned if ln]
    except Exception:
        commands = []

    if not commands:
        try:
            proc = subprocess.run([exe, "-lc", f"HISTTIMEFORMAT= history | tail -n {max_count}"],
                                  text=True, capture_output=True, cwd=os.getcwd())
            if proc.stdout:
                cleaned = [_clean_history_line(ln) for ln in proc.stdout.splitlines()]
                commands = [ln for ln in cleaned if ln]
        except Exception:
            commands = []

    if not commands:
        histfile = Path(os.getenv("HISTFILE") or (Path.home() / ".bash_history")).expanduser()
        if histfile.exists():
            try:
                commands = [
                    _clean_history_line(ln) or "" for ln in histfile.read_text(encoding="utf-8", errors="ignore").splitlines()
                ]
                commands = [ln for ln in commands if ln]
            except Exception:
                commands = []

    commands = [cmd for cmd in commands if cmd][:max_count]
    return [Command(text=cmd, output="") for cmd in commands]


def combine_user_messages(messages: List[str], summary: bool = False) -> str:
    user_messages = [msg.strip() for msg in messages if msg and msg.strip()]
    if summary:
        user_messages.append("Summarize the last command/output in 3-5 bullet points.")
    return "\n".join(user_messages).strip()


# ---------------------------
# Main CLI
# ---------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Explain your terminal output with optional multi-command context.")
    parser.add_argument("-x", "--last", type=int, default=None,
                        help="Number of most recent commands to include as context (alias: -x, --last, default env OUTEXPLAIN_MAX_COMMANDS).")
    parser.add_argument(
        "-m",
        "--message",
        "--query",
        dest="messages",
        action="append",
        default=[],
        help="Extra guidance or a direct question (alias: --query). Repeatable.",
    )
    parser.add_argument(
        "-s",
        "--summary",
        action="store_true",
        help="Skip troubleshooting and just summarize the last command/output.",
    )
    parser.add_argument("--provider", choices=["openai", "anthropic", "ollama"], help="Force a provider.")
    parser.add_argument("--model", type=str, help="LLM model to use.")
    parser.add_argument("--debug", action="store_true", help="Print debug information.")
    parser.add_argument("--debug-env", action="store_true", help="Print detected shell/terminal capabilities.")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"],
                        default=os.getenv("OUTEXPLAIN_LOG_LEVEL", "info"),
                        help="Set the log level for invocation history.")
    parser.add_argument("--no-log", action="store_true", help="Disable writing invocation history to disk.")
    parser.add_argument("--review", "-n", type=int, default=None,
                        help="Review the N most recent command/output pairs from the history log when live capture is unavailable.")
    args = parser.parse_args()

    # Detect shell
    shell = get_shell()
    term_info = detect_terminal_info(shell)
    symbols = choose_symbols(term_info)
    console = Console(color_system=_color_system_from_depth(term_info.color_depth))
    debug = (lambda text: console.print(f"[dim]outexplain | {text}[/dim]")) if args.debug else (lambda *_: None)

    if args.debug or args.debug_env:
        console.print(f"[dim]{format_terminal_info(term_info)}[/dim]")

    # Merge message + query
    user_message = combine_user_messages(args.messages, summary=args.summary)

    status_text = f"{symbols['info']} Trying my best..."
    with console.status(f"[bold green]{status_text}"):

        if (not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY")
                and not os.environ.get("OLLAMA_MODEL") and not args.provider):
            console.print(
                f"[bold red]{symbols['fail']} No model configured.[/bold red]\n"
                "Set OPENAI_API_KEY or ANTHROPIC_API_KEY, or provide an OLLAMA_MODEL.\n"
                "Tip: set OPENAI_MODEL=gpt-4o or run with --provider ollama --model llama3.1"
            )
            return

        stdin_data = ""
        try:
            if not sys.stdin.isatty():
                stdin_data = sys.stdin.read()
        except Exception:
            stdin_data = ""

        in_tmux_or_screen = bool(os.getenv("TMUX") or os.getenv("STY"))
        is_windows = platform.system() == "Windows"
        is_powershell = (shell.name in {"pwsh", "powershell"})
        is_bashlike = (shell.name in {"bash", "zsh"})

        max_requested = args.last if (isinstance(args.last, int) and args.last > 0) else None
        cap = max_requested or MAX_COMMANDS_DEFAULT

        commands: List[Command] = []
        terminal_context = ""

        if in_tmux_or_screen:
            terminal_context, commands = get_terminal_context(shell, max_commands=cap, return_commands=True)
        elif stdin_data.strip():
            terminal_context = f"<terminal_history>\n{stdin_data.strip()}\n</terminal_history>"
        elif is_windows and is_powershell:
            commands = _read_commands_from_ps_transcript(max_count=cap)
            if not commands:
                commands = _read_last_commands_from_ps_history(max_count=cap)
            if commands:
                commands = truncate_commands(commands, max_commands=cap)
                if _has_missing_output(commands):
                    console.print(f"[bold yellow]{symbols['warn']} Some command outputs are missing; context includes history only.[/bold yellow]")
                terminal_context = build_context_from_commands(commands, shell.prompt or "PS>")
        elif is_bashlike:
            commands = _read_bashlike_history(shell.path, max_count=cap)
            if commands:
                commands = truncate_commands(commands, max_commands=cap)
                if _has_missing_output(commands):
                    console.print(f"[bold yellow]{symbols['warn']} Some command outputs are missing; context includes history only.[/bold yellow]")
                terminal_context = build_context_from_commands(commands, shell.prompt or "$")

        if not terminal_context and args.review:
            review_commands, review_prompt = read_history(args.review)
            if review_commands:
                commands = review_commands
                terminal_context = build_context_from_commands(commands, review_prompt or shell.prompt or "$")
                console.print(f"[dim]{symbols['info']} Using stored history log.[/dim]")

        if not terminal_context:
            if is_windows and is_powershell:
                console.print(f"[bold yellow]{symbols['warn']} Couldn't read PSReadLine history.[/bold yellow]")
            elif is_bashlike:
                console.print(f"[bold yellow]{symbols['warn']} Could not retrieve recent history from bash/zsh.[/bold yellow]")
            else:
                console.print(f"[bold yellow]{symbols['warn']} No tmux/screen or input detected.[/bold yellow]")
            return

        append_history(commands, shell, enabled=not args.no_log, log_level=args.log_level)

        response = explain(terminal_context, user_message, provider=args.provider, model=args.model)

    console.print(response)


if __name__ == "__main__":
    main()
