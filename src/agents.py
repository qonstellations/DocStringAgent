"""Core docstring generation agent with hallucination-correction loop."""

from __future__ import annotations

import ast
import random
import re
import textwrap
import time

from langchain_core.messages import HumanMessage, SystemMessage

from src import config
from src.models import get_llm
from src.tools import FunctionAnalysis, analyze_function, validate_docstring_sections



class RateLimitError(Exception):
    """Raised when LLM rate limits are exceeded after retries."""
    pass


# ── System Prompt ───────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a Python docstring generation expert. Your ONLY job is to produce
Google-style docstrings for the function or class you are given.

STRICT RULES — violating ANY of these rules is a critical failure:

1. OUTPUT ONLY THE DOCSTRING — start with triple quotes and end with triple quotes.
   Do NOT include the function signature, body, or any code outside the docstring.
2. Use Google-style format with sections: Summary, Args, Returns/Yields, Raises,
   Warning (for mutable defaults), Note (for async/coroutine).
3. ONLY document behaviour that is EXPLICITLY present in the source code.
4. For the Raises section, ONLY list exceptions that appear in explicit `raise`
   statements or are well-known implied exceptions from builtins
   (e.g. open→FileNotFoundError, dict[key]→KeyError, int()→ValueError).
5. NEVER include "Raises: None" or invent exceptions not in the code.
6. NEVER narrow types when the code has no type hints. If a parameter has no
   annotation, describe it by its usage, not by an assumed type.
7. If the function is a GENERATOR (contains yield), use "Yields:" NOT "Returns:".
8. If the function is ASYNC, mention that it is a coroutine in the summary or
   in a Note section.
9. If a parameter has a MUTABLE DEFAULT (list, dict, set), add a Warning section.
10. Keep the summary line concise (one line if possible).
11. Triple-quote style: use triple double quotes (\"\"\").
"""

CORRECTION_PROMPT_TEMPLATE = """\
Your previous docstring had the following violations:

{violations}

Here is the original function source:
```python
{source}
```

Here is the AST analysis:
- Explicit raises: {raises}
- Builtin exception risks: {risks}
- Is async: {is_async}
- Is generator: {is_generator}
- Mutable defaults: {mutable_defaults}
- Parameters: {params}
- Return annotation: {return_annotation}

Regenerate the docstring fixing ALL violations. Output ONLY the corrected
docstring (triple-quoted).
"""


# ── Public API ──────────────────────────────────────────────────


def process_file(
    source: str,
    provider: str = "auto",
    model_name: str | None = None,
    temperature: float = config.TEMPERATURE,
) -> dict:
    """Process an entire Python file and add docstrings to all functions/classes.

    Args:
        source: Complete Python source code.
        provider: LLM provider — "ollama", "gemini", or "auto".
        model_name: Model identifier (None = provider default).
        temperature: Sampling temperature.

    Returns:
        Dict with keys:
            - ``original``: the input source
            - ``documented``: the output source with docstrings
            - ``functions_processed``: number of functions handled
            - ``corrections_made``: total correction passes used
    """
    llm = get_llm(provider=provider, model_name=model_name, temperature=temperature)

    tree = ast.parse(source)
    source_lines = source.splitlines()

    # Collect all function and class definitions (top-level + nested)
    targets: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            targets.append(node)

    # Sort by line number (descending) so we can splice bottom-up
    targets.sort(key=lambda n: n.lineno, reverse=True)

    total_corrections = 0
    processed = 0

    for node in targets:
        # Skip if already has a docstring
        if _has_docstring(node):
            continue

        analysis = analyze_function(node, source_lines)
        docstring, corrections = generate_docstring(analysis, llm)
        total_corrections += corrections

        if docstring:
            source_lines = _insert_docstring(source_lines, node, docstring)
            processed += 1
            # Rate limit delay to prevent 429 errors
            time.sleep(config.RATE_LIMIT_DELAY)

    documented = "\n".join(source_lines) + "\n"

    # Final syntax validation
    ast.parse(documented)

    return {
        "original": source,
        "documented": documented,
        "functions_processed": processed,
        "corrections_made": total_corrections,
    }


def generate_docstring(
    analysis: FunctionAnalysis,
    llm,
) -> tuple[str, int]:
    """Generate a validated docstring for a single function.

    Uses a correction loop: if validation fails, the LLM is re-prompted
    with specific violation instructions.  Maximum retries set by
    ``config.MAX_CORRECTION_PASSES``.

    Args:
        analysis: The static-analysis results for the function.
        llm: A LangChain BaseChatModel instance.

    Returns:
        A (docstring, correction_count) tuple.
    """
    user_prompt = _build_generation_prompt(analysis)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    corrections = 0
    docstring = None

    for attempt in range(1 + config.MAX_CORRECTION_PASSES):
        print(f"[DEBUG] Attempt {attempt+1}/{config.MAX_CORRECTION_PASSES + 1} for {analysis.name}")
        response = _invoke_no_retry(llm, messages)

        raw = response.content.strip()
        docstring = _extract_docstring(raw)

        if not docstring:
            # Could not parse a docstring from the response — retry
            messages.append(HumanMessage(
                content="Your response did not contain a valid triple-quoted docstring. "
                        "Please output ONLY the docstring wrapped in triple double quotes."
            ))
            corrections += 1
            continue

        violations = validate_docstring_sections(docstring, analysis)

        if not violations:
            return docstring, corrections

        if attempt < config.MAX_CORRECTION_PASSES:
            correction_msg = CORRECTION_PROMPT_TEMPLATE.format(
                violations="\n".join(f"  - {v}" for v in violations),
                source=analysis.source,
                raises=analysis.explicit_raises or "none",
                risks=analysis.builtin_exception_risks or "none",
                is_async=analysis.is_async,
                is_generator=analysis.is_generator,
                mutable_defaults=analysis.mutable_defaults or "none",
                params=analysis.parameters,
                return_annotation=analysis.return_annotation or "none",
            )
            messages.append(HumanMessage(content=correction_msg))
            corrections += 1

    # Return best effort after exhausting correction passes
    return docstring, corrections


def _invoke_no_retry(llm, messages) -> any:
    """Invoke LLM once; raise RateLimitError immediately on 429."""
    try:
        return llm.invoke(messages)
    except Exception as e:
        msg = str(e).lower()
        if "resource exhausted" in msg or "429" in msg:
            print("[ERROR] Rate limit hit immediately.")
            raise RateLimitError("Rate limit exceeded. Please try again later or switch models.")
        raise



# ── Helpers ─────────────────────────────────────────────────────


def _build_generation_prompt(analysis: FunctionAnalysis) -> str:
    """Build the initial user prompt for docstring generation."""
    kind = "class" if analysis.is_class else "function"
    parts = [
        f"Generate a Google-style docstring for the following Python {kind}:\n",
        f"```python\n{analysis.source}\n```\n",
        "AST analysis results:",
    ]

    if analysis.parameters:
        parts.append(f"  Parameters: {analysis.parameters}")
    if analysis.return_annotation:
        parts.append(f"  Return annotation: {analysis.return_annotation}")
    if analysis.is_async:
        parts.append("  ⚡ This is an ASYNC function — mention coroutine behaviour.")
    if analysis.is_generator:
        parts.append("  🔄 This is a GENERATOR — use 'Yields:' NOT 'Returns:'.")
    if analysis.explicit_raises:
        parts.append(f"  Explicit raises: {analysis.explicit_raises}")
    if analysis.builtin_exception_risks:
        parts.append(f"  Builtin exception risks: {analysis.builtin_exception_risks}")
    if analysis.mutable_defaults:
        parts.append(
            f"  ⚠️ Mutable defaults on: {analysis.mutable_defaults} — add a Warning section."
        )
    if not analysis.explicit_raises and not analysis.builtin_exception_risks:
        parts.append("  No exceptions detected — do NOT include a Raises section.")

    parts.append("\nOutput ONLY the docstring (triple-quoted). Nothing else.")
    return "\n".join(parts)


def _extract_docstring(text: str) -> str | None:
    """Extract a triple-quoted docstring from LLM output."""
    # Try to find """..."""
    match = re.search(r'"""(.*?)"""', text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try '''...'''
    match = re.search(r"'''(.*?)'''", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # If the text looks like a bare docstring without quotes
    stripped = text.strip().strip('"').strip("'").strip()
    if stripped and "\n" in stripped:
        return stripped

    return None


def _has_docstring(node: ast.AST) -> bool:
    """Check if a node already has a docstring."""
    if not hasattr(node, "body") or not node.body:
        return False
    first = node.body[0]
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )


def _insert_docstring(
    source_lines: list[str],
    node: ast.AST,
    docstring: str,
) -> list[str]:
    """Splice a docstring into source lines as the first body statement.

    Preserves indentation and does NOT touch decorators or signature.
    Handles single-line definitions (e.g. ``def f(): pass``) by first
    expanding them into multi-line form.
    """
    if not node.body:
        return source_lines

    first_body = node.body[0]
    def_line_idx = node.lineno - 1        # 0-indexed line of `def`/`class`
    body_line_idx = first_body.lineno - 1  # 0-indexed line of first body stmt

    # ── Handle single-line defs (body on same line as def) ──────
    if body_line_idx == def_line_idx:
        raw_line = source_lines[def_line_idx]
        # Find the colon that closes the signature
        colon_pos = raw_line.find(":", raw_line.find("def "))
        if colon_pos == -1:
            colon_pos = raw_line.find(":", raw_line.find("class "))
        if colon_pos == -1:
            return source_lines  # cannot parse — bail

        sig_part = raw_line[: colon_pos + 1]
        body_text = raw_line[colon_pos + 1 :].strip()
        def_indent = len(raw_line) - len(raw_line.lstrip())
        body_indent_str = " " * (def_indent + 4)

        # Replace the single line with two lines
        source_lines[def_line_idx] = sig_part
        source_lines.insert(def_line_idx + 1, f"{body_indent_str}{body_text}")
        body_line_idx = def_line_idx + 1

    # ── Determine indentation from the (now separate) body line ──
    body_line = source_lines[body_line_idx]
    indent = len(body_line) - len(body_line.lstrip())
    indent_str = " " * indent

    # ── Format the docstring ────────────────────────────────────
    ds_lines = docstring.split("\n")
    if len(ds_lines) == 1:
        formatted = f'{indent_str}"""{ds_lines[0]}"""'
        new_lines = [formatted]
    else:
        new_lines = [f'{indent_str}"""']
        for dl in ds_lines:
            if dl.strip():
                new_lines.append(f"{indent_str}{dl.strip()}")
            else:
                new_lines.append("")
        new_lines.append(f'{indent_str}"""')

    # Insert docstring before the first body statement
    result = source_lines[:body_line_idx] + new_lines + source_lines[body_line_idx:]
    return result
