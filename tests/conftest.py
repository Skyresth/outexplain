import pytest
from outexplain.utils import Shell


@pytest.fixture
def bash_history_text():
    return """
$ ls
file1.txt
$ echo done
done
$ git status
On branch main
""".strip()


@pytest.fixture
def zsh_history_text():
    return """
% ls
one.txt
% echo ready
ready
% git status
nothing to commit
""".strip()


@pytest.fixture
def powershell_history_text():
    return r"""
PS C:\\Users\\test> dir
file
PS C:\\Users\\test> echo ok
ok
PS C:\\Users\\test> Get-ChildItem
child
""".strip()


@pytest.fixture
def bash_shell():
    return Shell(path="/bin/bash", name="bash", prompt="$")


@pytest.fixture
def zsh_shell():
    return Shell(path="/bin/zsh", name="zsh", prompt="%")


@pytest.fixture
def powershell_shell():
    return Shell(path="C:/Program Files/PowerShell/7/pwsh.exe", name="powershell", prompt=">")
