"""`fr` command-line entry point."""

from pathlib import Path

import typer

from fitting_room.config import ConfigError, ConfigRoot, load_campaign

app = typer.Typer(
    help="fitting-room: benchmark models x harnesses on your own repo work.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """fitting-room: benchmark models x harnesses on your own repo work."""


@app.command()
def version() -> None:
    """Print the fitting-room version."""
    from fitting_room import __version__

    typer.echo(__version__)


@app.command()
def run(
    campaign: str = typer.Argument(..., help="Campaign name (configs/campaigns/<name>.toml)"),
    repo_root: Path = typer.Option(Path("."), help="fitting-room repo root"),
    results: Path = typer.Option(Path("results"), help="Where campaign results go"),
) -> None:
    """Validate a campaign and run every configuration in it through Harbor."""
    from fitting_room.outcomes import classify_trial_dir, tally
    from fitting_room.runner import run_campaign, trial_dirs

    root = ConfigRoot(repo_root / "configs")
    try:
        camp = load_campaign(campaign, root, repo_root)
        jobs = run_campaign(camp, repo_root / results, root)
    except ConfigError as err:
        typer.echo(f"Refusing to start campaign '{campaign}':\n{err}", err=True)
        raise typer.Exit(2) from None
    for job in jobs:
        t = tally([classify_trial_dir(d) for d in trial_dirs(job.job_dir)])
        rate = "n/a" if t.pass_rate is None else f"{t.pass_rate:.0%}"
        typer.echo(
            f"{job.run.name}: {t.passed} passed, {t.failed} failed, "
            f"{t.infra_errors} infrastructure errors (pass rate {rate}) -> {job.job_dir}"
        )
    if any(j.returncode != 0 for j in jobs):
        raise typer.Exit(1)


@app.command()
def mine(
    repo: list[str] = typer.Option([], help="Repo name to include (repeatable; default all)"),
    out: Path = typer.Option(Path("work/mining"), help="Output directory (gitignored)"),
) -> None:
    """Mine local agent session histories into reviewable task candidates."""
    from fitting_room.miner.pipeline import mine as run_mine

    stats = run_mine(repo, out)
    for key, value in stats.items():
        typer.echo(f"{key}: {value}")
    typer.echo(f"wrote {out / 'candidates.md'} and {out / 'candidates.jsonl'}")


@app.command()
def classify(
    limit: int = typer.Option(None, help="Label at most this many follow-ups (pilot runs)"),
    out: Path = typer.Option(Path("work/mining"), help="Mining output directory"),
    parallel: int = typer.Option(1, help="Concurrent GLM calls (mind the plan's rate limits)"),
) -> None:
    """Label mined follow-ups with GLM (model_error, misunderstanding, ...); cached.

    Uses GLM 5.3 Flash with thinking on, through Agent Vault (placeholder key).
    Re-run `fr mine` afterwards to rank candidates by model errors.
    """
    from fitting_room.miner.classify import classify as run_classify

    stats = run_classify(
        out / "candidates.jsonl", out / "followup-labels.jsonl", limit=limit, parallel=parallel
    )
    typer.echo(stats)


serve_app = typer.Typer(help="Start/stop benchmark serving profiles (local models).")
app.add_typer(serve_app, name="serve")


@serve_app.command("up")
def serve_up_cmd(
    profile: str,
    repo_root: Path = typer.Option(Path("."), help="fitting-room repo root"),
    listen: str = typer.Option("127.0.0.1:18080", help="host:port for llama-swap"),
) -> None:
    """Launch configs/serving/<profile>.yaml on its own port."""
    from fitting_room.serving.launcher import serve_up

    state = serve_up(profile, repo_root / "configs", repo_root / "work", listen)
    typer.echo(f"{profile} up on http://{state.listen} (windows pid {state.windows_pid})")


@serve_app.command("down")
def serve_down_cmd(
    profile: str, repo_root: Path = typer.Option(Path("."), help="fitting-room repo root")
) -> None:
    """Stop a profile started with `fr serve up`."""
    from fitting_room.serving.launcher import serve_down

    typer.echo(f"{profile} stopped" if serve_down(profile, repo_root / "work") else "not up")


if __name__ == "__main__":
    app()
