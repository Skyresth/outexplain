# Standard library
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# Local
from outexplain.utils import Command, Shell, sanitize_text

HISTORY_PATH = Path(os.getenv("OUTEXPLAIN_HISTORY_PATH", "")).expanduser()
if not HISTORY_PATH:
    HISTORY_PATH = Path.home() / ".outexplain" / "history.jsonl"

MAX_HISTORY_BYTES = int(os.getenv("OUTEXPLAIN_HISTORY_MAX_BYTES", "1048576"))


def _ensure_history_dir() -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _enforce_size_limit(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size <= MAX_HISTORY_BYTES:
            return
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        retained: list[str] = []
        total = 0
        for line in reversed(lines):
            total += len(line.encode("utf-8")) + 1  # account for newline
            if total > MAX_HISTORY_BYTES:
                break
            retained.append(line)
        retained = list(reversed(retained))
        path.write_text("\n".join(retained) + ("\n" if retained else ""), encoding="utf-8")
    except Exception:
        # Best-effort: ignore rotation errors
        return


def append_history(commands: List[Command], shell: Shell, enabled: bool = True, log_level: str = "info") -> None:
    if not enabled or not commands:
        return
    _ensure_history_dir()
    timestamp = datetime.now(timezone.utc).isoformat()
    shell_info = {"name": shell.name, "path": shell.path, "prompt": shell.prompt}
    try:
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            for command in commands:
                entry = {
                    "timestamp": timestamp,
                    "log_level": log_level,
                    "shell": shell_info,
                    "command": sanitize_text(command.text),
                    "output": sanitize_text(command.output),
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _enforce_size_limit(HISTORY_PATH)
    except Exception:
        # Avoid interrupting CLI usage on logging issues
        return


def read_history(limit: int) -> Tuple[List[Command], Optional[str]]:
    if limit <= 0 or not HISTORY_PATH.exists():
        return [], None
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except Exception:
        return [], None

    commands: List[Command] = []
    last_prompt: Optional[str] = None
    for line in lines:
        try:
            entry = json.loads(line)
            command_text = sanitize_text(entry.get("command", ""))
            output_text = sanitize_text(entry.get("output", ""))
            commands.append(Command(command_text, output_text))
            if not last_prompt:
                shell_info = entry.get("shell") or {}
                last_prompt = shell_info.get("prompt")
        except Exception:
            continue
    return commands, last_prompt
