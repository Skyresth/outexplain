# Standard library
import os
import sys
import argparse
import platform
import subprocess
from typing import Literal, Optional, List
from pathlib import Path
from shutil import which

# Third party
from rich.console import Console

# Local
from outexplain.utils import (
    get_shell,
    get_terminal_context,
    explain,
    detect_terminal_info,
    format_terminal_info,
    choose_symbols,
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


# ---------------------------
# PowerShell helpers
# ---------------------------
def _pwsh_available() -> Optional[str]:
    for exe in ("pwsh", "powershell"):
        if which(exe):
            return exe
    return None


def _read_last_commands_from_ps_history(max_count: int) -> List[str]:
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
    return [ln.strip() for ln in lines if
            ln.strip() and not ln.lower().startswith(("outexplain", "python -m outexplain"))][-max_count:]


def _rerun_and_capture_in_pwsh(command: str) -> str:
    exe = _pwsh_available()
    if not exe:
        return ""
    ps_cmd = f'{command} 2>&1 3>&1 4>&1 5>&1 6>&1 | Out-String'
    try:
        proc = subprocess.run([exe, "-NoLogo", "-NoProfile", "-Command", ps_cmd],
                              text=True, capture_output=True, cwd=os.getcwd())
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        return ""


# ---------------------------
# Bash / Git Bash / Zsh helpers
# ---------------------------
def _rerun_and_capture_in_bashlike(shell_path: Optional[str], command: str) -> str:
    exe = shell_path or "bash"
    try:
        proc = subprocess.run([exe, "-lc", f"{command} 2>&1"],
                              text=True, capture_output=True, cwd=os.getcwd())
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        return ""


def _get_last_command_from_bashlike(shell_path: Optional[str]) -> Optional[str]:
    """
    Try to retrieve the last command from a bash-like shell.
    1) Try `fc -ln -1` in a login shell (works in many setups).
    2) Fallback: read ~/.bash_history or ~/.zsh_history directly.
    """
    exe = shell_path or "bash"

    # --- Method 1: fc -ln -1 ---
    try:
        proc = subprocess.run([exe, "-lc", "fc -ln -1"],
                              text=True, capture_output=True, cwd=os.getcwd())
        cmd = proc.stdout.strip()
        if cmd:
            return cmd
    except Exception:
        pass

    # --- Method 2: read history file ---
    histfile = Path(os.getenv("HISTFILE") or (Path.home() / ".bash_history")).expanduser()
    if not histfile.exists():
        return None
    try:
        lines = histfile.read_text(encoding="utf-8", errors="ignore").splitlines()
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            if ln.lower().startswith(("outexplain", "python -m outexplain")):
                continue
            return ln
    except Exception:
        return None

    return None


# ---------------------------
# Build terminal context
# ---------------------------
def _build_context(prev_cmds: List[str], last_cmd: str, output: str, prompt: str) -> str:
    previous = "\n".join(f"{prompt} {c}" for c in prev_cmds) if prev_cmds else ""
    context = "<terminal_history>\n"
    context += "<previous_commands>\n" + previous + "\n</previous_commands>\n"
    context += "\n<last_command>\n"
    context += f"{prompt} {last_cmd}\n{(output or '').strip()}"
    context += "\n</last_command>\n</terminal_history>"
    return context


# ---------------------------
# Main CLI
# ---------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Explain your terminal output with optional multi-command context.")
    parser.add_argument("-x", "--last", type=int, default=None,
                        help="Number of most recent commands to include as context (e.g. -x 5).")
    parser.add_argument("-m", "--message", type=str, default="",
                        help="Extra message to guide the explanation (e.g. -m 'why did npm fail?').")
    parser.add_argument("--query", type=str, default="", help="Alias of --message (will be combined).")
    parser.add_argument("--provider", choices=["openai", "anthropic", "ollama"], help="Force a provider.")
    parser.add_argument("--model", type=str, help="LLM model to use.")
    parser.add_argument("--debug", action="store_true", help="Print debug information.")
    parser.add_argument("--debug-env", action="store_true", help="Print detected shell/terminal capabilities.")
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
    user_message = (args.message or "").strip()
    if args.query.strip():
        user_message = (user_message + "\n" + args.query.strip()).strip()

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

        if in_tmux_or_screen:
            terminal_context = get_terminal_context(shell, max_commands=args.last)
        elif stdin_data.strip():
            terminal_context = f"<terminal_history>\n{stdin_data.strip()}\n</terminal_history>"
        elif is_windows and is_powershell:
            cap = args.last or 3
            hist_cmds = _read_last_commands_from_ps_history(max_count=cap)
            if not hist_cmds:
                console.print(f"[bold yellow]{symbols['warn']} Couldn't read PSReadLine history.[/bold yellow]")
                return
            prev_cmds, last_cmd = hist_cmds[:-1], hist_cmds[-1]
            output = _rerun_and_capture_in_pwsh(last_cmd) or "(no output captured)"
            terminal_context = _build_context(prev_cmds, last_cmd, output, prompt="PS>")
        elif is_bashlike:
            last_cmd = _get_last_command_from_bashlike(shell.path)
            if not last_cmd:
                console.print(f"[bold yellow]{symbols['warn']} Could not retrieve last command.[/bold yellow]")
                return
            if last_cmd.lower().startswith(("outexplain", "python -m outexplain")):
                console.print(f"[bold yellow]{symbols['warn']} Last command was outexplain itself.[/bold yellow]")
                return
            output = _rerun_and_capture_in_bashlike(shell.path, last_cmd) or "(no output captured)"
            terminal_context = _build_context([], last_cmd, output, prompt="$")
        else:
            console.print(f"[bold yellow]{symbols['warn']} No tmux/screen or input detected.[/bold yellow]")
            return

        response = explain(terminal_context, user_message, provider=args.provider, model=args.model)

    console.print(response)


if __name__ == "__main__":
    main()
