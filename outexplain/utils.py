# Standard library
import os
import re
import sys
import platform
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from collections import namedtuple
from subprocess import check_output, run, CalledProcessError, DEVNULL
from typing import List, Optional

# Third party
from ollama import chat
from psutil import Process, NoSuchProcess
from openai import OpenAI
from anthropic import Anthropic
from rich.markdown import Markdown

# Local
from outexplain.prompts import EXPLAIN_PROMPT, ANSWER_PROMPT

# --------------------
# Configuration / Const
# --------------------
MAX_CHARS = int(os.getenv("OUTEXPLAIN_MAX_CHARS", "10000"))
MAX_COMMANDS_DEFAULT = int(os.getenv("OUTEXPLAIN_MAX_COMMANDS", "3"))
MAX_HISTORY_LINES = int(os.getenv("OUTEXPLAIN_MAX_HISTORY", "5000"))

SHELLS = {"bash", "fish", "zsh", "csh", "tcsh", "powershell", "pwsh"}

Shell = namedtuple("Shell", ["path", "name", "prompt"])
Command = namedtuple("Command", ["text", "output"])

# Correct ANSI escape pattern (strip control codes)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# ----------- Small helpers -----------
def count_chars(text: str) -> int:
    return len(text)

def truncate_chars(text: str, reverse: bool = False) -> str:
    return text[-MAX_CHARS:] if reverse else text[:MAX_CHARS]

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s or "")

# --------------- Shell resolution ---------------
def get_shell_name(shell_path: Optional[str] = None) -> Optional[str]:
    if not shell_path:
        return None
    base = os.path.basename(shell_path).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    alias_map = {"sh": "bash", "ksh": "bash", "cmd": "powershell"}
    base = alias_map.get(base, base)
    if base in {"powershell", "pwsh"}:
        return "pwsh" if base == "pwsh" else "powershell"
    return base if base in SHELLS else None

def get_shell_name_and_path() -> tuple[Optional[str], Optional[str]]:
    env_path = os.environ.get("SHELL") or os.environ.get("TF_SHELL")
    if name := get_shell_name(env_path):
        return name, env_path
    try:
        proc = Process(os.getpid())
        while proc and proc.pid > 0:
            pname = proc.name().lower()
            if pname.endswith(".exe"):
                pname = pname[:-4]
            if pname in SHELLS:
                return pname, pname
            proc = proc.parent()
    except NoSuchProcess:
        pass
    return get_shell_name(env_path), env_path

def _run(cmd: list[str]) -> Optional[str]:
    try:
        return subprocess.check_output(cmd, text=True, stderr=DEVNULL).rstrip("\n")
    except Exception:
        return None

def get_shell_prompt(shell_name: Optional[str], shell_path: Optional[str]) -> Optional[str]:
    if not shell_name or not shell_path:
        return None
    if shell_name == "bash":
        return _run([shell_path, "-lc", 'echo -n "${PS1@P}"'])
    if shell_name == "zsh":
        return _run([shell_path, "-lc", 'print -Pn "$PS1"'])
    if shell_name == "fish":
        return _run([shell_path, "-lc", "functions -q fish_prompt; fish_prompt"])
    if shell_name in {"csh", "tcsh"}:
        return _run([shell_path, "-c", "echo -n $prompt"])
    if shell_name in {"pwsh", "powershell"}:
        return _run([shell_path, "-NoProfile", "-Command", "(& prompt)"])
    return None

# ---------------- Pane / Output IO ----------------
def get_pane_output() -> str:
    """Capture text from the current tmux/screen pane."""
    output_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, mode="w+") as temp_file:
            output_file = temp_file.name
        if os.getenv("TMUX"):
            cmd = ["tmux", "capture-pane", "-p", "-S", f"-{MAX_HISTORY_LINES}"]
            with open(output_file, "w", encoding="utf-8", errors="replace") as f:
                run(cmd, stdout=f, text=True)
        elif os.getenv("STY"):
            cmd = ["screen", "-X", "hardcopy", "-h", output_file]
            check_output(cmd, text=True)
        else:
            return ""
        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except CalledProcessError:
        return ""
    finally:
        if output_file and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass

# ---------------- Parsing commands ----------------
def looks_like_command_line(line: str) -> bool:
    s = strip_ansi(line).rstrip()
    return bool(s) and (s.endswith("$") or s.endswith("#") or s.endswith(">"))

def get_commands(pane_output: str, shell: Shell, max_commands: Optional[int] = None) -> List[Command]:
    commands: List[Command] = []
    buffer: List[str] = []
    prompt_raw = (shell.prompt or "").strip()
    prompt_cmp = strip_ansi(prompt_raw)
    cap = max_commands if (isinstance(max_commands, int) and max_commands > 0) else None
    for raw in reversed(pane_output.splitlines()):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        line_cmp = strip_ansi(line)
        is_prompt_line, cmd_text = False, ""
        if prompt_cmp and prompt_cmp in line_cmp:
            parts = line_cmp.rsplit(prompt_cmp, 1)
            if len(parts) == 2:
                cmd_text = parts[1].strip()
                is_prompt_line = True
        elif looks_like_command_line(line_cmp):
            cmd_text = line_cmp.split()[-1] if " " in line_cmp else line_cmp
            is_prompt_line = True
        if is_prompt_line:
            command = Command(cmd_text, "\n".join(reversed(buffer)).strip())
            commands.append(command)
            buffer.clear()
            if cap and len(commands) >= cap:
                break
            continue
        buffer.append(line)
    filtered = [c for c in commands if not c.text.startswith("outexplain")]
    return list(reversed(filtered))

def truncate_commands(commands: List[Command], max_commands: Optional[int] = None) -> List[Command]:
    cap = max_commands if (isinstance(max_commands, int) and max_commands > 0) else None
    commands = commands[-cap:] if cap else commands
    num_chars, truncated = 0, []
    for command in commands:
        cchars = count_chars(command.text)
        if cchars + num_chars > MAX_CHARS:
            break
        num_chars += cchars
        out_lines = []
        for line in reversed(command.output.splitlines()):
            lchars = count_chars(line)
            if lchars + num_chars > MAX_CHARS:
                break
            out_lines.append(line)
            num_chars += lchars
        output = "\n".join(reversed(out_lines))
        truncated.append(Command(command.text, output))
    return truncated

def truncate_pane_output(output: str) -> str:
    hit_non_empty = False
    lines: List[str] = []
    for line in reversed(output.splitlines()):
        if line and line.strip():
            hit_non_empty = True
        if hit_non_empty:
            lines.append(line)
    if lines:
        lines = lines[1:]  # drop invocation line
    output = "\n".join(reversed(lines))
    return truncate_chars(output, reverse=True).strip()

def command_to_string(command: Command, shell_prompt: Optional[str] = None) -> str:
    shell_prompt = shell_prompt if shell_prompt else "$"
    command_str = f"{shell_prompt} {command.text}"
    output = command.output.strip()
    if output:
        command_str += f"\n{output}"
    else:
        command_str += "\n(output missing)"
    return command_str

def format_output(output: str) -> Markdown:
    return Markdown(output, code_theme="monokai",
                    inline_code_lexer="python", inline_code_theme="monokai")

# ---------------- LLM provider runners ----------------
def run_anthropic(system_message: str, user_message: str) -> str:
    anthropic = Anthropic()
    response = anthropic.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system=system_message,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text

def run_openai(system_message: str, user_message: str, model: Optional[str] = None) -> str:
    openai = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
    response = openai.chat.completions.create(
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        model=model or os.getenv("OPENAI_MODEL") or "gpt-4o",
        temperature=0.2,
        max_tokens=1200,
    )
    return response.choices[0].message.content

def run_ollama(system_message: str, user_message: str, model: Optional[str] = None) -> str:
    response = chat(
        model=model or os.getenv("OLLAMA_MODEL"),
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
    )
    return response.message.content

def get_llm_provider() -> str:
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OLLAMA_MODEL"):
        return "ollama"
    raise ValueError("No model configured.")

# ---------------- Terminal detection ----------------
@dataclass
class TerminalInfo:
    os: str
    platform: str
    is_tty: bool
    shell_name: str | None
    shell_path: str | None
    shell_prompt: str | None
    term: str | None
    term_program: str | None
    term_program_version: str | None
    emulator: str | None
    parent_chain: list[str]
    is_tmux: bool
    is_screen: bool
    is_wsl: bool
    is_windows_terminal: bool
    color_depth: int
    supports_hyperlinks: bool
    supports_emoji: bool

def _bool_env(name: str) -> bool:
    v = os.getenv(name)
    return v not in (None, "", "0", "false", "False")

def _detect_color_depth(term: str | None) -> int:
    colorterm = (os.getenv("COLORTERM") or "").lower()
    if colorterm in {"truecolor", "24bit"}:
        return 24
    if term and "256color" in term:
        return 256
    if os.getenv("WT_SESSION"):
        return 24
    return 16

def _detect_hyperlinks(term: str | None) -> bool:
    if os.getenv("WT_SESSION"):
        return True
    tp = os.getenv("TERM_PROGRAM") or ""
    if tp in {"iTerm.app", "WezTerm", "Hyper", "vscode"}:
        return True
    if term and ("kitty" in term or "xterm-kitty" in term):
        return True
    vte = os.getenv("VTE_VERSION")
    try:
        if vte and int(vte) >= 5000:
            return True
    except ValueError:
        pass
    if os.getenv("KONSOLE_VERSION"):
        return True
    if os.getenv("TMUX") and "kitty" in (term or ""):
        return True
    return False

def _detect_emoji_support() -> bool:
    if os.getenv("WT_SESSION"):
        return True
    sysname = platform.system()
    return sysname in {"Darwin", "Linux", "Windows"}

def _get_parent_chain() -> list[str]:
    names: list[str] = []
    try:
        proc = Process(os.getpid())
        while proc and proc.pid > 0:
            names.append(proc.name())
            proc = proc.parent()
    except Exception:
        pass
    return names

def _guess_emulator_from_env() -> str | None:
    if os.getenv("WT_SESSION"):
        return "WindowsTerminal"
    tp = os.getenv("TERM_PROGRAM")
    if tp:
        return tp
    term = os.getenv("TERM") or ""
    if "kitty" in term:
        return "kitty"
    if "xterm" in term:
        return "xterm"
    return None

def _guess_emulator_from_process_chain(chain: list[str]) -> str | None:
    low = [n.lower() for n in chain]
    candidates = ["windowsterminal", "wezterm", "iterm2", "alacritty",
                  "hyper", "kitty", "gnome-terminal", "konsole", "xterm",
                  "terminator", "tilix", "tmux", "screen", "conhost",
                  "powershell", "pwsh", "cmd", "code"]
    for cand in candidates:
        for n in low:
            if cand in n:
                return cand
    return None

def detect_terminal_info(shell: Shell) -> TerminalInfo:
    sysname = platform.system()
    term = os.getenv("TERM")
    term_program = os.getenv("TERM_PROGRAM")
    term_program_version = os.getenv("TERM_PROGRAM_VERSION")
    parent_chain = _get_parent_chain()
    emulator = _guess_emulator_from_process_chain(parent_chain) or _guess_emulator_from_env()
    return TerminalInfo(
        os=sysname,
        platform=sys.platform,
        is_tty=sys.stdout.isatty(),
        shell_name=shell.name,
        shell_path=shell.path,
        shell_prompt=shell.prompt,
        term=term,
        term_program=term_program,
        term_program_version=term_program_version,
        emulator=emulator,
        parent_chain=parent_chain,
        is_tmux=_bool_env("TMUX"),
        is_screen=_bool_env("STY"),
        is_wsl=bool(os.getenv("WSL_DISTRO_NAME") or os.getenv("WSL_INTEROP")),
        is_windows_terminal=_bool_env("WT_SESSION"),
        color_depth=_detect_color_depth(term),
        supports_hyperlinks=_detect_hyperlinks(term),
        supports_emoji=_detect_emoji_support(),
    )

def format_terminal_info(info: TerminalInfo) -> str:
    lines = []
    data = asdict(info)
    chain = data.pop("parent_chain", [])
    data["parent_chain"] = " > ".join(chain[:8]) + (" > …" if len(chain) > 8 else "")
    for k, v in data.items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines)

def choose_symbols(info: TerminalInfo) -> dict[str, str]:
    return {"ok": "✅", "warn": "⚠️", "fail": "❌", "info": "💡"} if info.supports_emoji else \
        {"ok": "[OK]", "warn": "[!]", "fail": "[X]", "info": "[i]"}

def get_shell() -> Shell:
    name, path = get_shell_name_and_path()
    prompt = get_shell_prompt(name, path)
    return Shell(path, name, prompt)

def get_terminal_context(shell: Shell, max_commands: Optional[int] = None) -> str:
    pane_output = get_pane_output()
    if not pane_output and not sys.stdin.isatty():
        try:
            pane_output = sys.stdin.read()
        except Exception:
            pane_output = ""
    if not pane_output:
        return "<terminal_history>No terminal output found.</terminal_history>"
    if not shell.prompt:
        return f"<terminal_history>\n{truncate_pane_output(pane_output)}\n</terminal_history>"
    cap = max_commands if (isinstance(max_commands, int) and max_commands > 0) else MAX_COMMANDS_DEFAULT
    commands = get_commands(pane_output, shell, max_commands=cap)
    commands = truncate_commands(commands, max_commands=cap)
    if not commands:
        return "<terminal_history>No terminal output found.</terminal_history>"
    return build_context_from_commands(commands, shell.prompt)

def build_context_from_commands(commands: List[Command], shell_prompt: Optional[str]) -> str:
    if not commands:
        return "<terminal_history>No terminal output found.</terminal_history>"
    previous_commands, last_command = commands[:-1], commands[-1]
    context = "<terminal_history>\n"
    context += "<previous_commands>\n"
    context += "\n".join(command_to_string(c, shell_prompt) for c in previous_commands)
    context += "\n</previous_commands>\n"
    context += "\n<last_command>\n"
    context += command_to_string(last_command, shell_prompt)
    context += "\n</last_command>\n"
    context += "</terminal_history>"
    return context

def build_query(context: str, query: Optional[str] = None) -> str:
    if not (query and query.strip()):
        query = "Explain the last command's output. Use previous commands as context, but focus on the last command."
    return f"{context}\n\n{query}"

def explain(context: str, query: Optional[str] = None, provider: Optional[str] = None, model: Optional[str] = None) -> Markdown:
    system_message = EXPLAIN_PROMPT if not query else ANSWER_PROMPT
    user_message = build_query(context, query)
    provider_name = provider or get_llm_provider()
    if provider_name == "anthropic":
        return format_output(run_anthropic(system_message, user_message))
    if provider_name == "ollama":
        return format_output(run_ollama(system_message, user_message, model=model))
    return format_output(run_openai(system_message, user_message, model=model))
