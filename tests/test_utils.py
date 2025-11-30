import builtins
from types import SimpleNamespace

import pytest

from outexplain import outexplain
from outexplain.utils import (
    Command,
    MAX_CHARS,
    build_query,
    get_commands,
    get_llm_provider,
    truncate_commands,
)


def test_get_commands_respects_max_commands(bash_history_text, bash_shell):
    commands = get_commands(bash_history_text, bash_shell, max_commands=2)
    assert [cmd.text for cmd in commands] == ["echo done", "git status"]
    assert commands[0].output.strip() == "done"
    assert commands[1].output.strip() == "On branch main"


def test_get_commands_powershell_prompt(powershell_history_text, powershell_shell):
    commands = get_commands(powershell_history_text, powershell_shell, max_commands=3)
    assert commands[-1].text == "Get-ChildItem"
    assert commands[0].text == "dir"
    assert commands[0].output.strip() == "file"


def test_get_commands_zsh_prompt(zsh_history_text, zsh_shell):
    commands = get_commands(zsh_history_text, zsh_shell, max_commands=1)
    assert [cmd.text for cmd in commands] == ["git status"]
    assert commands[0].output.strip() == "nothing to commit"


def test_truncate_commands_respects_max_chars(monkeypatch):
    monkeypatch.setattr("outexplain.utils.MAX_CHARS", 20)
    commands = [
        Command("ls", "first line\nsecond line"),
        Command("very-long-command-name", "output line one\noutput line two"),
    ]
    truncated = truncate_commands(commands, max_commands=2)
    assert len(truncated) == 1
    assert truncated[0].text == "ls"
    assert truncated[0].output == "second line"


def test_get_llm_provider_raises_without_env(monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        get_llm_provider()


def test_build_query_combines_messages(monkeypatch):
    context = "<terminal_history>example</terminal_history>"
    combined = outexplain.combine_user_messages(["First message", "Second"], summary=False)
    assert combined == "First message\nSecond"

    combined_summary = outexplain.combine_user_messages(["First"], summary=True)
    assert "Summarize the last command" in combined_summary

    query = outexplain.combine_user_messages([""], summary=False)
    assert query == ""
    assert build_query(context, query) == f"{context}\n\nExplain the last command's output. Use previous commands as context, but focus on the last command."
