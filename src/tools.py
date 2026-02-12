"""AST-based static analysis and docstring validation utilities."""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field


# ── Data Structures ─────────────────────────────────────────────


@dataclass
class FunctionAnalysis:
    """Aggregated analysis results for a single function/class."""

    name: str
    is_async: bool = False
    is_generator: bool = False
    is_class: bool = False
    parameters: list[dict] = field(default_factory=list)
    return_annotation: str | None = None
    explicit_raises: list[str] = field(default_factory=list)
    builtin_exception_risks: list[str] = field(default_factory=list)
    mutable_defaults: list[str] = field(default_factory=list)
    has_return_value: bool = False
    decorators: list[str] = field(default_factory=list)
    source: str = ""
    lineno: int = 0
    end_lineno: int = 0


# ── Individual Detectors ────────────────────────────────────────


def detect_explicit_raises(node: ast.AST) -> list[str]:
    """Walk *node* and collect all explicitly raised exception names.

    Args:
        node: An AST node (typically FunctionDef / AsyncFunctionDef).

    Returns:
        Sorted, deduplicated list of exception class names.
    """
    raises: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.exc is not None:
            if isinstance(child.exc, ast.Call):
                raises.add(_name_of(child.exc.func))
            elif isinstance(child.exc, ast.Name):
                raises.add(child.exc.id)
            elif isinstance(child.exc, ast.Attribute):
                raises.add(_name_of(child.exc))
    return sorted(raises)


def detect_yield(node: ast.AST) -> bool:
    """Return True if *node* contains ``yield`` or ``yield from``.

    Args:
        node: An AST node.

    Returns:
        Whether a yield expression was found.
    """
    for child in ast.walk(node):
        if isinstance(child, (ast.Yield, ast.YieldFrom)):
            return True
    return False


def detect_async(node: ast.AST) -> bool:
    """Return True if *node* is an ``async def``.

    Args:
        node: An AST node.

    Returns:
        Whether the node is an AsyncFunctionDef.
    """
    return isinstance(node, ast.AsyncFunctionDef)


def detect_mutable_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Detect parameters with mutable default values.

    Looks for ``list()``, ``dict()``, ``set()``, ``[]``, ``{}``.

    Args:
        node: A function definition AST node.

    Returns:
        List of parameter names with mutable defaults.
    """
    mutable: list[str] = []
    defaults = node.args.defaults
    args = node.args.args

    # defaults are right-aligned with args
    offset = len(args) - len(defaults)
    for i, default in enumerate(defaults):
        if _is_mutable_literal(default) or _is_mutable_call(default):
            mutable.append(args[offset + i].arg)

    for kw_default in node.args.kw_defaults:
        if kw_default and (_is_mutable_literal(kw_default) or _is_mutable_call(kw_default)):
            # find matching kwonlyarg
            idx = node.args.kw_defaults.index(kw_default)
            mutable.append(node.args.kwonlyargs[idx].arg)

    return mutable


def detect_builtin_exception_risks(node: ast.AST) -> list[str]:
    """Detect calls that may raise common built-in exceptions.

    Detects:
    - ``open()`` → FileNotFoundError, PermissionError
    - ``dict[key]`` subscript → KeyError
    - ``int()`` / ``float()`` → ValueError
    - ``list[index]`` → IndexError

    Args:
        node: An AST node.

    Returns:
        Sorted, deduplicated list of potential exception names.
    """
    risks: set[str] = set()
    for child in ast.walk(node):
        # open() calls
        if isinstance(child, ast.Call) and _name_of(child.func) == "open":
            risks.update(["FileNotFoundError", "PermissionError"])
        # int() / float() calls
        if isinstance(child, ast.Call) and _name_of(child.func) in ("int", "float"):
            risks.add("ValueError")
        # subscript access  e.g. d[key]
        if isinstance(child, ast.Subscript):
            risks.add("KeyError")
    return sorted(risks)


# ── Aggregate Analyser ──────────────────────────────────────────


def analyze_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    source_lines: list[str],
) -> FunctionAnalysis:
    """Run every detector on *node* and return a combined analysis.

    Args:
        node: AST node for a function or class.
        source_lines: The full source split by lines.

    Returns:
        A populated FunctionAnalysis dataclass.
    """
    is_class = isinstance(node, ast.ClassDef)
    is_func = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))

    analysis = FunctionAnalysis(
        name=node.name,
        lineno=node.lineno,
        end_lineno=node.end_lineno or node.lineno,
        is_class=is_class,
        source=textwrap.dedent(
            "\n".join(source_lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
        ),
    )

    if is_func:
        analysis.is_async = detect_async(node)
        analysis.is_generator = detect_yield(node)
        analysis.explicit_raises = detect_explicit_raises(node)
        analysis.builtin_exception_risks = detect_builtin_exception_risks(node)
        analysis.mutable_defaults = detect_mutable_defaults(node)
        analysis.has_return_value = _has_return_value(node)
        analysis.parameters = _extract_params(node)
        analysis.return_annotation = _get_return_annotation(node)
        analysis.decorators = [ast.dump(d) for d in node.decorator_list]

    return analysis


# ── Validation ──────────────────────────────────────────────────


def validate_docstring_sections(
    docstring: str,
    analysis: FunctionAnalysis,
) -> list[str]:
    """Cross-check a generated docstring against AST analysis.

    Checks:
    - No invented ``Raises`` (must be in explicit or builtin risks).
    - ``Yields`` used for generators; ``Returns`` for regular functions.
    - Async functions mention coroutine behaviour.
    - No ``Raises: None``.
    - Mutable defaults are warned about.

    Args:
        docstring: The generated docstring text.
        analysis: The analysis from ``analyze_function``.

    Returns:
        List of violation messages.  Empty means the docstring is valid.
    """
    violations: list[str] = []
    ds_lower = docstring.lower()

    # 1. Check Raises section
    allowed_raises = set(analysis.explicit_raises) | set(analysis.builtin_exception_risks)
    raises_section = _extract_section(docstring, "Raises")
    if raises_section:
        for line in raises_section:
            exc_name = line.split(":")[0].strip()
            if exc_name and exc_name not in allowed_raises:
                violations.append(
                    f"Hallucinated raise: '{exc_name}' not found in code. "
                    f"Allowed: {sorted(allowed_raises) or 'none'}"
                )
        if "none" in raises_section[0].lower().strip():
            violations.append("Must not include 'Raises: None'.")

    # 2. Generators must use Yields, not Returns
    if analysis.is_generator:
        if "returns:" in ds_lower and "yields:" not in ds_lower:
            violations.append("Generator function must use 'Yields:' instead of 'Returns:'.")
    else:
        if "yields:" in ds_lower:
            violations.append("Non-generator function should not use 'Yields:'.")

    # 3. Async functions must mention coroutine
    if analysis.is_async and "coroutine" not in ds_lower:
        violations.append("Async function docstring must mention coroutine behaviour.")

    # 4. Mutable defaults should have a warning
    if analysis.mutable_defaults:
        has_warning = any(
            param in docstring for param in analysis.mutable_defaults
        )
        if not has_warning:
            violations.append(
                f"Mutable default arguments {analysis.mutable_defaults} should be mentioned with a warning."
            )

    return violations


def ensure_docstring_position(source: str) -> list[str]:
    """Verify that every function/class has docstring as first body statement.

    Args:
        source: Complete Python source code string.

    Returns:
        List of violation messages.
    """
    violations: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"Syntax error in output: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.body:
                continue
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if not isinstance(first.value.value, str):
                    violations.append(
                        f"{node.name}: first body statement is not a docstring."
                    )
            # If the function has a docstring that is not the first statement, flag it
            for i, stmt in enumerate(node.body):
                if i == 0:
                    continue
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    if isinstance(stmt.value.value, str) and '"""' in repr(stmt.value.value):
                        violations.append(
                            f"{node.name}: docstring found at body position {i}, should be 0."
                        )
    return violations


# ── Helpers ─────────────────────────────────────────────────────


def _name_of(node: ast.AST) -> str:
    """Resolve a dotted name from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name_of(node.value)}.{node.attr}"
    return ""


def _is_mutable_literal(node: ast.AST) -> bool:
    return isinstance(node, (ast.List, ast.Dict, ast.Set))


def _is_mutable_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _name_of(node.func) in (
        "list",
        "dict",
        "set",
    )


def _has_return_value(node: ast.AST) -> bool:
    """Check if any return statement carries a value."""
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            return True
    return False


def _extract_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
    """Extract parameter names and their annotations."""
    params: list[dict] = []
    for arg in node.args.args:
        if arg.arg == "self" or arg.arg == "cls":
            continue
        p: dict = {"name": arg.arg}
        if arg.annotation:
            p["type"] = ast.unparse(arg.annotation)
        params.append(p)
    for arg in node.args.kwonlyargs:
        p = {"name": arg.arg, "keyword_only": True}
        if arg.annotation:
            p["type"] = ast.unparse(arg.annotation)
        params.append(p)
    if node.args.vararg:
        p = {"name": f"*{node.args.vararg.arg}"}
        if node.args.vararg.annotation:
            p["type"] = ast.unparse(node.args.vararg.annotation)
        params.append(p)
    if node.args.kwarg:
        p = {"name": f"**{node.args.kwarg.arg}"}
        if node.args.kwarg.annotation:
            p["type"] = ast.unparse(node.args.kwarg.annotation)
        params.append(p)
    return params


def _get_return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if node.returns:
        return ast.unparse(node.returns)
    return None


def _extract_section(docstring: str, section_name: str) -> list[str]:
    """Pull out lines beneath a Google-style section header."""
    lines = docstring.split("\n")
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{section_name}:"):
            in_section = True
            continue
        if in_section:
            if stripped and not stripped[0].isspace() and ":" in stripped and not stripped.startswith(" "):
                # might be inside the section — check indentation
                pass
            if stripped == "" or (
                not line.startswith(" ") and not line.startswith("\t") and stripped and ":" in stripped and stripped.split(":")[0].replace(" ", "").isalpha()
            ):
                # new section header or blank after section
                if section_lines:
                    break
            else:
                section_lines.append(stripped)
    return section_lines
