# Contributing

Thanks for improving **outexplain**! This guide summarizes how to set up the project, run tests, and craft prompts that match the expected style.

## Environment setup

1. Create a virtual environment (e.g. `python -m venv .venv && source .venv/bin/activate`).
2. Install dependencies: `pip install -e .` (or `pip install -r requirements.txt` if you prefer a frozen set).
3. Configure at least one provider so the CLI can talk to an LLM:
   - `export OPENAI_API_KEY=...` **or** `export ANTHROPIC_API_KEY=...` **or** `export OLLAMA_MODEL=<model>`
   - Optional: `OPENAI_MODEL` / `OPENAI_BASE_URL` for custom OpenAI-compatible endpoints.
4. Run `python -m outexplain --help` to verify the CLI loads with your environment variables.

## Running tests

Automated tests are being added incrementally. Once they are in place, run them with:

```bash
pytest
```

For quick validation before sending a PR, run a lightweight sanity check:

```bash
python -m compileall outexplain
```

## Prompt/style expectations

- Keep prompts concise and goal-oriented; prefer direct questions like `-m "why did npm install fail?"`.
- Use Markdown in assistant responses with fenced code blocks for commands/snippets; bold only for warnings or key takeaways.
- When adding new prompts or examples, default to short summaries unless the output is complex.

## Contributing workflow

1. Open or pick an issue and describe the change you plan to make.
2. Add or update tests relevant to the change (see the test matrix in the README for inspiration).
3. Run the test suite and sanity checks, then open a PR describing what changed and how it was validated.
