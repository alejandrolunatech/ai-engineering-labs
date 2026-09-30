"""ai-golden-path command line interface.

`new` exit codes:
  0  capability created
  1  destination exists or filesystem error (nothing existing was modified)
  2  invalid capability name or usage error (nothing was created)
  3  template violates the capability contract (platform bug; nothing was created)

`upgrade` exit codes (its own contract; never a target runtime's codes):
  0  dry-run plan ready or up_to_date, or a clean apply succeeded
  1  the plan has conflicts (apply refuses, nothing written), or an apply
     filesystem failure / stale plan (rolled back)
  2  usage error, unknown target version or unsupported upgrade edge
  3  invalid provenance, incompatible or invalid contract, modified source
     platform snapshot, or invalid platform template
"""

from __future__ import annotations

from pathlib import Path

import typer

from golden_path import scaffold, upgrade as upgrades

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
    """Create ./<name>/ from the current capability template. Refuses to overwrite."""
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


@app.command()
def upgrade(
    to: str = typer.Option(..., "--to", help="Released template version to upgrade to, e.g. 0.2.0."),
    apply: bool = typer.Option(False, "--apply", help="Perform the plan. Refused if it has any conflict."),
    diff: bool = typer.Option(False, "--diff", help="Show bounded platform (BASE -> TARGET) diffs."),
) -> None:
    """Plan (default: dry run) or apply an upgrade of the capability in the current directory.

    The source version is read from capability.yaml (metadata.template_version).
    """
    root = Path.cwd()
    try:
        plan = upgrades.plan_upgrade(root, to)
    except upgrades.UpgradeError as exc:
        typer.echo(f"error: {exc.describe()}", err=True)
        raise typer.Exit(exc.exit_code) from None
    except scaffold.ScaffoldError:
        typer.echo("error: platform_template_invalid: a released template failed to render or validate", err=True)
        raise typer.Exit(3) from None
    except OSError as exc:
        typer.echo(f"error: filesystem_error: {type(exc).__name__} while reading the project", err=True)
        raise typer.Exit(1) from None

    typer.echo(upgrades.format_plan(plan, diff=diff), nl=False)
    if plan.status == "up_to_date":
        return
    if not apply:
        typer.echo("dry run: nothing was written." + ("" if plan.conflicts else " Re-run with --apply to perform this plan."))
        raise typer.Exit(1 if plan.conflicts else 0)

    try:
        written = upgrades.apply_plan(root, plan)
    except upgrades.UpgradeError as exc:
        typer.echo(f"error: refusing to apply: {exc.describe()}" if isinstance(exc, upgrades.ConflictsRefused)
                   else f"error: {exc.describe()}", err=True)
        raise typer.Exit(exc.exit_code) from None
    typer.echo(f"applied: {len(written)} file(s); {upgrades.MANIFEST} written last")
    typer.echo(f"metadata.template_version: {plan.target}")
    typer.echo("Next: install requirements.txt and run the project's own checks and tests. "
               "The upgrade did not execute any product code.")
