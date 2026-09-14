"""``ari harness`` — see what the pool declares, and what can answer a question.

This is the operator-facing half of the pool. It reads declarations and prints
them; the ranking it shows comes from ``ari.harness_select``, which by
construction cannot reach a score. Selection stays a decision the operator makes
from a table that shows its work, so `select` prints and exits rather than
binding anything.
"""
from __future__ import annotations

import typer

harness_app = typer.Typer(
    name="harness",
    help="Inspect the harness pool and see which harnesses can answer a question.")


@harness_app.command("list")
def cmd_list() -> None:
    """What each registered harness says it is for."""
    from ari.harness_registry import available_tasks, load

    tasks = available_tasks()
    if not tasks:
        typer.echo("no harnesses are registered under <workspace>/harnesses/")
        raise typer.Exit(1)

    for task in tasks:
        d = load(task).declares
        typer.echo(f"\n{task}")
        typer.echo(f"  question    : {d.question or '(undeclared)'}")
        typer.echo(f"  denominator : {d.denominator or '(undeclared)'}")
        if d.band_is_measured:
            reps = f", {d.resolves_reps} reps" if d.resolves_reps else ""
            typer.echo(f"  resolves    : {d.resolves * 100:.3f}%  "
                       f"(measured {d.resolves_measured_on}{reps})")
        else:
            typer.echo("  resolves    : NOT MEASURED — this harness has never "
                       "been characterised, so it cannot be promised to resolve "
                       "anything")
        typer.echo(f"  cost        : "
                   + (f"{d.cost_s:.1f}s per scoring" if d.cost_s is not None
                      else "(undeclared)"))
        typer.echo(f"  sees        : {', '.join(d.sees) or '(undeclared)'}")
        typer.echo(f"  blind to    : {', '.join(d.blind_to) or '(undeclared)'}")


@harness_app.command("select")
def cmd_select(
    resolve: float = typer.Option(
        None, help="smallest effect the study must see, as a FRACTION "
                   "(0.005 = 0.5%). A harness whose band is wider cannot answer "
                   "the question."),
    budget_s: float = typer.Option(None, help="seconds per scoring you can afford"),
    must_see: str = typer.Option(
        "", help="comma-separated axes the question depends on; a harness blind "
                 "to any of them is refused however good its band"),
    have: str = typer.Option(
        "", help="comma-separated capabilities this machine actually has"),
    denominator: str = typer.Option("", help="required denominator, if fixed"),
) -> None:
    """Rank the pool against a requirement, and say why for every harness.

    Exits 2 when nothing qualifies. That is a result rather than an error: it
    means the requirement is wrong or the pool is missing a harness that does
    not exist yet. Running the closest one anyway produces a number, not an
    answer.
    """
    from ari.harness_registry import available_tasks, load
    from ari.harness_select import Requirement, format_table, rank

    req = Requirement(
        resolve=resolve, budget_s=budget_s,
        must_see=tuple(x.strip() for x in must_see.split(",") if x.strip()),
        have=tuple(x.strip() for x in have.split(",") if x.strip()),
        denominator=denominator.strip(),
    )
    pool = [(t, load(t).declares) for t in available_tasks()]
    if not pool:
        typer.echo("no harnesses are registered")
        raise typer.Exit(1)

    verdicts = rank(pool, req)
    typer.echo(format_table(verdicts))
    if not any(v.eligible for v in verdicts):
        raise typer.Exit(2)
