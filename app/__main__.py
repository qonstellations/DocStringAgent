"""CLI entry point for DocStringAgent.

Usage:
    uv run python -m app generate <file>      # add docstrings to a file
    uv run python -m app serve                # launch the web UI
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from app import config

cli = typer.Typer(
    name="docstringagent",
    help="🧠 DocStringAgent — AI-powered Python docstring generator",
    add_completion=False,
)
console = Console()


@cli.command()
def generate(
    file: Path = typer.Argument(..., help="Path to a Python file"),
    provider: str = typer.Option("auto", help="LLM provider: auto | ollama | gemini"),
    model: str | None = typer.Option(None, help="Model name override"),
    temperature: float = typer.Option(config.TEMPERATURE, help="Sampling temperature"),
    output: Path | None = typer.Option(None, "-o", help="Output path (default: overwrite in-place)"),
    diff: bool = typer.Option(False, "--diff", help="Show diff instead of writing"),
) -> None:
    """Add Google-style docstrings to a Python file."""
    from app.agents import process_file

    if not file.exists():
        console.print(f"[red]Error:[/red] File not found: {file}")
        raise typer.Exit(1)

    source = file.read_text(encoding="utf-8")

    console.print(Panel(f"[bold cyan]DocStringAgent[/bold cyan] processing [yellow]{file}[/yellow]"))

    with console.status("[bold green]Analysing and generating docstrings…"):
        result = process_file(
            source=source,
            provider=provider,
            model_name=model,
            temperature=temperature,
        )

    documented = result["documented"]
    funcs = result["functions_processed"]
    corrections = result["corrections_made"]

    console.print(
        f"\n[green]✓[/green] Processed [bold]{funcs}[/bold] function(s), "
        f"[bold]{corrections}[/bold] correction pass(es) used.\n"
    )

    if diff:
        console.print(Syntax(documented, "python", theme="monokai", line_numbers=True))
    else:
        out_path = output or file
        out_path.write_text(documented, encoding="utf-8")
        console.print(f"[green]✓[/green] Written to [bold]{out_path}[/bold]")


@cli.command()
def serve(
    port: int = typer.Option(config.DEFAULT_PORT, help="Port to serve on"),
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
) -> None:
    """Launch the DocStringAgent web interface."""
    import uvicorn

    console.print(
        Panel(
            f"[bold cyan]DocStringAgent Web UI[/bold cyan]\n"
            f"Open [link=http://localhost:{port}]http://localhost:{port}[/link]",
            border_style="green",
        )
    )
    uvicorn.run("app.server:app", host=host, port=port, reload=True)


@cli.command()
def models() -> None:
    """List available LLM models."""
    from app.models import list_ollama_models, detect_default_model

    console.print("\n[bold cyan]Available Models[/bold cyan]\n")

    ollama = list_ollama_models()
    if ollama:
        console.print("[green]Ollama (local):[/green]")
        for m in ollama:
            console.print(f"  • {m}")
    else:
        console.print("[dim]Ollama: not running or no models pulled[/dim]")

    console.print()
    if config.GEMINI_API_KEY:
        console.print(f"[green]Gemini (cloud):[/green] {config.DEFAULT_GEMINI_MODEL}")
    else:
        console.print("[dim]Gemini: GEMINI_API_KEY not set[/dim]")

    default_prov, default_model = detect_default_model()
    console.print(f"\n[bold]Auto-detected default:[/bold] {default_prov} / {default_model}\n")


if __name__ == "__main__":
    cli()
