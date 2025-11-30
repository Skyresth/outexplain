# outexplain

**CLI that explains the output of your last command.**

Just type `outexplain` and an LLM will help you understand whatever's in your terminal. You'll be surprised how useful this can be. It can help you:

- Understand stack traces
- Decipher error codes
- Fix incorrect commands
- Summarize logs

## Installation

```bash
> pipx install outexplain-cli
```

<!-- On MacOS or Linux, you can install via Homebrew:

```bash
> brew install outexplain
```

On other systems, you can install using pip:

```bash
> pipx install outexplain-cli
``` -->

Once installed, you can use OpenAI or Claude as your LLM provider. Just add the appropriate API key to your environment:

```bash
> export OPENAI_API_KEY="..."
> export ANTHROPIC_API_KEY="..."
```

You can also use a local model with Ollama. Just add the model name that's being served to your environment:

```bash
> export OLLAMA_MODEL="..."
```

If you're using OpenAI, you can customize your model and API URL by adding the following to your environment:

```bash
> export OPENAI_MODEL="..." # Default to "gpt-4o"
> export OPENAI_BASE_URL="..." # Default to None
```

## Usage

`outexplain` must be used inside a `tmux` or `screen` session to capture the last command's output. To use it, just type `outexplain` after running a command:

```bash
> git create-pr
git: 'create-pr' is not a git command.
> outexplain
```

You'll quickly get a brief explanation of the issue:

```
This error occurs because Git doesn't have a built-in `create-pr` command.
To create a pull request, you typically need to:

1. Push your branch to the remote repository
2. Use the GitHub web interface
```

If you have a _specific question_ about your last command, you can include a query:

```bash
> brew install pip
...
> outexplain -m "how do i add this to my PATH variable?"
```

### CLI quickstart

- Explaining the last command/output:

  ```bash
  outexplain
  ```

- Asking a specific question (use `-m/--message` or its alias `--query`):

  ```bash
  outexplain -m "why did npm install fail?"
  ```

- Reviewing and analyzing the last 3 stored interactions when live capture is unavailable:

  ```bash
  outexplain -n 3 -m "which of these failed and why?"
  ```

- Summary-only mode (no troubleshooting, just the gist):

  ```bash
  outexplain --summary
  ```

- Forcing provider/model selection:

  ```bash
  outexplain --provider ollama --model llama3.1
  ```

You can pass `-m/--message/--query` multiple times to add more context. Use `-x/--last` to increase how many previous commands are sent as context when available.

## Flujos por shell

- **Bash / Zsh (Linux/macOS):**
  - Ejecuta `outexplain` dentro de `tmux` o `screen` para capturar la salida del panel.
  - Si tmux/screen no están disponibles, `-n <N>` lee los últimos comandos almacenados en el historial interno de `outexplain`.
  - Usa `-x <N>` para controlar cuántos comandos previos se incluyen desde el historial interactivo.

- **PowerShell (Windows):**
  - Intenta leer la transcripción más reciente en `~/Documents/PowerShell_transcript*.txt` o `PSReadLine/ConsoleHost_history.txt`.
  - No requiere tmux/screen, pero solo se capturarán los comandos que estén en el historial; la salida puede faltar y se avisará en amarillo.

- **Git Bash / MSYS2:**
  - Se comporta como bash, pero a veces el historial no es accesible si se ejecuta fuera de una consola interactiva.
  - Ejecuta dentro de `tmux`/`screen` cuando sea posible o usa `-n` para revisar el historial guardado.

## Variables de entorno

- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`: proveedores en la nube.
- `OLLAMA_MODEL`: nombre del modelo local servido por Ollama.
- `OPENAI_MODEL` y `OPENAI_BASE_URL`: personaliza modelo/endpoint de OpenAI (por defecto `gpt-4o`).
- `OUTEXPLAIN_MAX_COMMANDS`, `OUTEXPLAIN_MAX_CHARS`, `OUTEXPLAIN_MAX_HISTORY`: ajusta cuántos comandos y cuántos caracteres se envían al LLM.

## Resolución de problemas comunes

- **Historial inaccesible:** si ves una advertencia amarilla, ejecuta dentro de `tmux`/`screen` o usa `-n` para leer el log persistente.
- **Sin tmux/screen instalados:** instala uno de ellos o pásale el historial por `stdin`, por ejemplo `history | tail -n 50 | outexplain`.
- **Claves de API ausentes:** configura alguna de las variables anteriores o define `--provider`/`--model` para usar Ollama.

## Matriz de pruebas

- **Automatizadas (sugeridas):**
  - Pruebas unitarias de parseo de historial (bash y PowerShell) validando extracción de comandos y salida.
  - Pruebas de truncamiento que respeten `OUTEXPLAIN_MAX_CHARS` en comandos y salidas largas.
  - Pruebas de construcción de contexto verificando formato `<previous_commands>`/`<last_command>` y preservación de prompts.

- **Manuales recomendadas:**
  - `outexplain` dentro de `tmux` tras un comando fallido, confirmando que se captura la salida completa.
  - `outexplain -n 3 -m "why did these fail?"` sin tmux para validar la lectura del log.
  - `outexplain --summary` para comprobar que devuelve solo un resumen breve.
  - `outexplain --provider ollama --model llama3.1` verificando selección explícita de proveedor/modelo.

## Roadmap

1. [If possible,](https://stackoverflow.com/questions/24283097/reusing-output-from-last-command-in-bash/75629157#75629157) drop the requirement of being inside a tmux or screen session.
2. Add a `--fix` option to automatically execute a command suggested by `outexplain`.
3. Add `outexplain` to Homebrew.
4. Make some unit tests.
