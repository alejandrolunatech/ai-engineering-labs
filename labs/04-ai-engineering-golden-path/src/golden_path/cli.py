"""ai-golden-path command line interface.

Exit codes:
  0  capability created
  1  destination exists or filesystem error (nothing existing was modified)
  2  invalid capability name or usage error (nothing was created)
  3  template violates the capability contract (platform bug; nothing was created)
"""

from __future__ import annotations

from pathlib import Path

import typer

from golden_path import scaffold

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """AI Engineering Golden Path: scaffold capabilities from a versioned template."""


@app.command()
def new(
    name: str = typer.Argument(
        ..., help="Capability name: 3-40 chars, lowercase letters/digits, single hyphens."
    ),
) -> None:
    """Create ./<name>/ from template capability@0.1.0. Refuses to overwrite."""
    try:
        destination, files = scaffold.new_capability(name, Path.cwd())
    except scaffold.InvalidNameError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    except scaffold.TemplateContractError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from None
    except scaffold.DestinationExistsError as exc:
        typer.echo(f"error: {exc}; refusing to overwrite", err=True)
        raise typer.Exit(1) from None
    except OSError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    typer.echo(f"Created {name}/ from template {scaffold.TEMPLATE_ID}@{scaffold.TEMPLATE_VERSION}:")
    for relative in files:
        typer.echo(f"  {name}/{relative}")
    typer.echo("Review spec.purpose and spec.data.sensitivity in capability.yaml: they are starter defaults.")
