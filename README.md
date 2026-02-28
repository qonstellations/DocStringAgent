# DocStringAgent

An **AI-powered Python docstring generation agent** that automatically generates clean, Google-style docstrings for your Python code. Paste code, upload a file, or point to a server path — the agent analyses your code with AST introspection, calls an LLM, validates the output, and self-corrects up to 2 times until the docstring is accurate.

> 🏆 **Hackathon Winner** — Won at the **Epoch x Nasiko Agentic AI Bootcamp** held at **IIIT Sricity**, February 2026.

---

## Agent Design

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│  Source Code │────▶│  AST Analyzer │────▶│  LLM Generation  │
└──────────────┘     └───────────────┘     └────────┬─────────┘
                                                    │
                                           ┌────────▼─────────┐
                                           │   Validator      │
                                           │  (rule-based)    │
                                           └────────┬─────────┘
                                                    │
                                        ┌───────────▼──────────┐
                                        │  Violations found?   │
                                        └───┬──────────────┬───┘
                                          Yes              No
                                            │               │
                                  ┌─────────▼──────┐  ┌─────▼───────┐
                                  │ Correction Loop│  │  Insert     │
                                  │ (max 2 passes) │  │  Docstring  │
                                  └─────────┬──────┘  └─────────────┘
                                            │
                                     back to LLM
```

### Core Pipeline

1. **AST Analysis** (`app/tools.py`) — Statically inspects each function/class to extract:
   - Parameters and type annotations
   - Explicit `raise` statements
   - Built-in implied exceptions (e.g. `open()` → `FileNotFoundError`, `dict[key]` → `KeyError`)
   - `async` / generator (`yield`) detection
   - Mutable default arguments (`list`, `dict`, `set`)

2. **LLM Prompting** (`app/agents.py`) — Sends the source code and analysis results to an LLM with a strict system prompt enforcing Google-style rules. The prompt forbids hallucination: the LLM may only document behaviour that is **explicitly present** in the code.

3. **Validation** (`app/tools.py`) — Checks the generated docstring against the AST analysis:
   - Has `Yields:` for generators? Has `Returns:` for non-generators?
   - Does the `Raises:` section only list actually-raised exceptions?
   - Is there a `Warning:` for mutable defaults?
   - Does it mention coroutine behaviour for async functions?

4. **Self-Correction Loop** — If validation fails, the agent sends the violations back to the LLM with the original source and AST data, requesting a corrected docstring. This repeats for up to **2 correction passes**.

5. **Docstring Insertion** — The validated docstring is spliced into the source code at the correct position, preserving indentation, decorators, and surrounding code.

### Multi-Model Support

| Provider | Models | Notes |
|----------|--------|-------|
| **Gemini** (cloud) | `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-2.5-pro` | Requires `GEMINI_API_KEY` in `.env` |
| **Ollama** (local) | Auto-detected from running Ollama server | No API key needed; runs fully offline |

The UI automatically discovers local Ollama models on startup and offers them alongside cloud models.

---

## Usage Instructions

### Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** package manager
- A **Gemini API key** (for cloud models) and/or a running **Ollama** instance (for local models)

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/DocStringAgent.git
cd DocStringAgent

# Install dependencies
uv sync
uv venv

# Edit .env and add your GEMINI_API_KEY
```

### Web UI

```bash
uv run -m src serve
# Open http://localhost:8000
```

The web interface provides three input methods:
- **Paste Code** — paste Python code directly
- **Upload File** — drag & drop or browse for a `.py` file
- **Server Path** — enter a file or directory path on the server

Select a model from the dropdown (Gemini cloud or local Ollama), click **Generate Docstrings**, and view results in Modified / Original / Side-by-Side views.

### CLI

```bash
# Generate docstrings for a single file
uv run -m src generate path/to/file.py

# Generate and overwrite the file in-place
uv run -m src generate path/to/file.py --overwrite

# List available models
uv run -m src models
```

### Docker

You can also run the application using Docker:

```bash
# Using Docker Compose (Recommended)
docker compose up --build

# Using Docker directly
docker build -t docstring-agent .
docker run -p 8000:8000 docstring-agent
```

### Project Structure

```
DocStringAgent/
├── src/
│   ├── __main__.py      # CLI commands (generate, serve, models)
│   ├── agents.py        # LLM prompting, validation loop, docstring insertion
│   ├── config.py        # Configuration constants, env loading
│   ├── models.py        # LLM factory (Ollama/Gemini), model discovery
│   ├── server.py        # FastAPI backend, API routes
│   └── tools.py         # AST analysis, validation rules
├── static/
│   ├── index.html       # Web UI
│   ├── styles.css       # Dark-mode stylesheet
│   └── app.js           # Frontend logic
├── Dockerfile           # Docker build instructions
├── docker-compose.yaml  # Docker Compose configuration
├── pyproject.toml
└── .env                 # API keys (not committed)
```

---

## Assumptions & Limitations

### Assumptions

- Input code is **syntactically valid Python**. The agent will reject code that fails `ast.parse()`.
- For cloud models, a valid **`GEMINI_API_KEY`** is set in the `.env` file.
- For local models, **Ollama is running** and accessible at `http://localhost:11434` (configurable via `OLLAMA_BASE_URL`).
- Functions and classes that **already have docstrings** are skipped (no overwriting of existing docs).

### Limitations

- **No cross-function context** — the agent documents each function/class in isolation. It does not trace call chains or understand broader application context.
- **Correction ceiling** — the self-correction loop is capped at **2 passes**. Complex or ambiguous functions may still produce imperfect docstrings after exhausting retries.
- **Single-file scope** — the agent processes one file at a time (directory mode iterates files individually). It does not resolve cross-file imports or dependencies.
- **No type inference** — if a parameter lacks type annotations, the agent describes it by usage rather than guessing a type. This is by design to avoid hallucination, but means less specific docs for untyped code.
- **LLM variability** — output quality depends on the chosen model. Larger models (e.g. Gemini 2.5 Pro, Qwen 14B) generally produce better results than smaller ones.
- **Rate limits** — cloud models (Gemini) are subject to API rate limits and quotas. Processing large directories may hit these limits.

---

## License

MIT
