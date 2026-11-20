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
    quota_cap: int = typer.Option(
        None, help="Optional: pause when the 5-hour GLM window reaches this % (off by default)"
    ),
) -> None:
    """Label mined follow-ups with GLM (model_error, misunderstanding, ...); cached.

    Uses GLM 5.3 Flash with thinking on, through Agent Vault (placeholder key).
    Re-run `fr mine` afterwards to rank candidates by model errors.
    """
    from fitting_room.miner.classify import classify as run_classify

    stats = run_classify(
        out / "candidates.jsonl",
        out / "followup-labels.jsonl",
        limit=limit,
        parallel=parallel,
        quota_cap=quota_cap,
    )
    typer.echo(stats)


@app.command()
def reviews(
    repo: list[str] = typer.Option([], help="Repo name to include (repeatable; default all)"),
    out: Path = typer.Option(Path("work/mining/reviews.jsonl"), help="Output file"),
) -> None:
    """Extract review passes (review-mcp, Claude review agents) with what followed."""
    from fitting_room.miner.reviews import write_reviews

    for key, value in write_reviews(out, repo or None).items():
        typer.echo(f"{key}: {value}")


@app.command("label-reviews")
def label_reviews_cmd(
    limit: int = typer.Option(None, help="Label at most this many reviews (pilot runs)"),
    parallel: int = typer.Option(1, help="Concurrent GLM calls"),
    quota_cap: int = typer.Option(
        None, help="Optional: pause when the 5-hour GLM window reaches this % (off by default)"
    ),
    mining: Path = typer.Option(Path("work/mining"), help="Mining output directory"),
) -> None:
    """Label extracted reviews with GLM: real_bug_fixed, false_positive, ...; cached."""
    from fitting_room.miner.review_labels import label_reviews

    stats = label_reviews(
        mining / "reviews.jsonl",
        mining / "review-labels.jsonl",
        limit=limit,
        parallel=parallel,
        quota_cap=quota_cap,
    )
    typer.echo(stats)


@app.command()
def triage(
    per_big_repo: int = typer.Option(200, help="Episodes sampled from each large repo"),
    parallel: int = typer.Option(2, help="Concurrent GLM calls (keep total <= 2)"),
    mining: Path = typer.Option(Path("work/mining"), help="Mining output directory"),
) -> None:
    """Triage mined episodes as task material with GLM (task statement, work type, size,
    grading, GPU, verdict); cached in triage.jsonl."""
    from fitting_room.miner.triage import triage as run_triage

    stats = run_triage(
        mining / "candidates.jsonl", mining / "triage.jsonl",
        per_big_repo=per_big_repo, parallel=parallel,
    )  # fmt: skip
    typer.echo(stats)


calibrate_app = typer.Typer(help="Blind human check of GLM follow-up labels.")
app.add_typer(calibrate_app, name="calibrate")


@calibrate_app.command("sample")
def calibrate_sample(
    mining: Path = typer.Option(Path("work/mining"), help="Mining output directory"),
) -> None:
    """Write work/mining/calibration/check.md (blind) and key.jsonl."""
    from fitting_room.miner.calibrate import write_sample

    out = mining / "calibration"
    stats = write_sample(mining / "candidates.jsonl", mining / "followup-labels.jsonl", out)
    typer.echo(f"{stats['items']} items -> {out / 'check.md'} (available: {stats['available']})")


@calibrate_app.command("score")
def calibrate_score(
    mining: Path = typer.Option(Path("work/mining"), help="Mining output directory"),
    current: bool = typer.Option(
        False, help="Score against the current prompt version's labels for the same items"
    ),
) -> None:
    """Compare your answers in check.md with GLM's labels."""
    from fitting_room.miner.calibrate import relabel_key, score

    override = None
    if current:
        override = relabel_key(
            mining / "calibration",
            mining / "candidates.jsonl",
            mining / "followup-labels.jsonl",
        )
    s = score(mining / "calibration", override)

    def pct(x):
        return "n/a" if x is None else f"{x:.0%}"

    typer.echo(f"answered {s.answered} (unclear {s.unclear}), unanswered {s.unanswered}")
    typer.echo(f"GLM 'agent fell short' precision: {pct(s.model_error_precision)}")
    typer.echo(f"errors GLM missed: {s.missed_errors}")
    kappa = "n/a" if s.kappa is None else f"{s.kappa:.2f}"
    typer.echo(f"agreement: {pct(s.agreement)}, kappa: {kappa} (bar: >=80%, >=0.6)")
    for d in s.disagreements:
        typer.echo(f"  item {d['item']}: you={d['you']} glm={d['glm']} ({d['why']})")


task_app = typer.Typer(help="Task authoring helpers.")
app.add_typer(task_app, name="task")


@task_app.command("materialize")
def task_materialize(
    task_dir: Path = typer.Argument(..., help="Task directory (contains task.toml)"),
) -> None:
    """Write environment/repo/ as `git archive` of [metadata] repo at start_commit."""
    from fitting_room.tasks.materialize import MaterializeError, materialize

    try:
        m = materialize(task_dir)
    except MaterializeError as err:
        typer.echo(f"error: {err}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"{m.repo}@{m.commit[:12]}: {m.files} files -> {m.dest}")
    if m.excluded:
        typer.echo(f"excluded by configs/repos/{m.repo}.toml: {m.excluded} files")
    if m.stripped:
        typer.echo(f"stripped: {', '.join(m.stripped)}")
    if m.submodules:
        typer.echo("warning: repo has submodules; their contents are not in the snapshot")


env_app = typer.Typer(help="Provision and inspect canonical repo environments.")
app.add_typer(env_app, name="env")

store_app = typer.Typer(help="Manage the benchmark store.")
app.add_typer(store_app, name="store")


harness_app = typer.Typer(help="Provision pinned harness installations.")
app.add_typer(harness_app, name="harness")


@harness_app.command("ensure")
def harness_ensure(name: str, version: str) -> None:
    """Install a harness once in the benchmark store."""
    from fitting_room.harness_store import ensure_harness
    from fitting_room.store import store_path

    try:
        path = ensure_harness(name, version, store_path())
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(path)


@env_app.command("ensure")
def env_ensure(
    repo: str,
    repo_root: Path = typer.Option(Path("."), help="fitting-room repo root"),
    offline: bool = typer.Option(False, help="Use cached inputs without downloading"),
) -> None:
    """Provision the environment pinned in configs/repos/<repo>.toml."""
    import json

    from fitting_room.bench_native import ensure_environment
    from fitting_room.store import store_path
    from fitting_room.tasks.materialize import MaterializeError

    try:
        manifest = ensure_environment(
            repo, store_path(), repo_root / "configs/repos", offline=offline
        )
    except (OSError, ValueError, MaterializeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(manifest, indent=2))


@env_app.command("check")
def env_check(
    task: Path,
    repo_root: Path = typer.Option(Path("."), help="fitting-room repo root"),
) -> None:
    """Report historical lock differences without changing the store."""
    import json

    from fitting_room.bench_env import check_task
    from fitting_room.tasks.materialize import MaterializeError

    try:
        diagnostic = check_task(task, repo_root / "configs/repos")
    except (OSError, ValueError, MaterializeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(diagnostic, indent=2))


@store_app.command("gc")
def store_gc(
    repo_root: Path = typer.Option(Path("."), help="fitting-room repo root"),
    apply: bool = typer.Option(False, "--apply", help="Remove the listed entries"),
) -> None:
    """Preview obsolete environments and unused harness or toolkit installs."""
    from fitting_room.store import store_path
    from fitting_room.store_gc import collect_store
    from fitting_room.tasks.materialize import MaterializeError

    try:
        paths = collect_store(store_path(), ConfigRoot(repo_root / "configs"), apply=apply)
    except (OSError, ValueError, ConfigError, MaterializeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    for path in paths:
        typer.echo(f"{'removed' if apply else 'unused'} {path}")
    if not paths:
        typer.echo("No unused entries found")


@app.command()
def doctor(
    repo_root: Path = typer.Option(Path("."), help="fitting-room repo root"),
    results: Path = typer.Option(Path("results"), help="Campaign results directory"),
) -> None:
    """Check rootless Podman and benchmark storage locations."""
    from fitting_room.podman_host import check_storage, podman_host_env
    from fitting_room.store import check_uv_filesystem, store_path, uv_cache

    try:
        check_uv_filesystem(store_path(), uv_cache())
        paths = check_storage(repo_root / "tasks", repo_root / results, podman_host_env())
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    for label, path in paths.items():
        typer.echo(f"{label} = {path}")


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
