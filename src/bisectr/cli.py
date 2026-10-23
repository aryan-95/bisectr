from __future__ import annotations
import os, subprocess, sys
from typing import List, Optional
import typer

from . import probe, report, store
from .bisect import run_bisect
from .config import load
from .gate import run_gate

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _kv(items):
    return dict(i.split("=", 1) for i in (items or []))


def _image(cfg, ref):
    return ref if ":" in ref else f"{cfg.infra.image_repo}:{ref}"


def _auto_baseline(cfg, branch):
    shas = subprocess.check_output(["git", "rev-list", branch, "-n", "50"], text=True).split()
    for s in shas:
        if probe.image_exists(cfg, s):
            return s
    typer.echo("no commit on the main branch has an image in ECR")
    raise typer.Exit(2)


@app.command()
def gate(config: str = "bisectr.yaml",
         candidate: str = typer.Option(...),
         baseline: str = "auto",
         main_branch: str = "origin/main",
         cand_env: Optional[List[str]] = typer.Option(None),
         base_env: Optional[List[str]] = typer.Option(None),
         pr: int = 0, post: bool = False, no_cache: bool = False):
    """Run candidate vs baseline probes side by side and print the verdict."""
    cfg = load(config)
    if baseline == "auto":
        baseline = _auto_baseline(cfg, main_branch)
    for ref in (candidate, baseline):
        if ":" not in ref and not probe.image_exists(cfg, ref):
            typer.echo(f"No image tagged {ref} in ECR. Commit your changes, then run ./scripts/push_images.sh "
                       f"(it pushes an image for the current HEAD).")
            raise typer.Exit(2)
    res = run_gate(cfg, (_image(cfg, candidate), _kv(cand_env)),
                   (_image(cfg, baseline), _kv(base_env)), use_cache=not no_cache)
    md = report.comment_markdown(res, cfg)
    typer.echo(md)
    store.save_run("gate", res)
    if post and pr:
        report.post_pr_comment(os.environ["GITHUB_REPOSITORY"], pr, md, os.environ["GITHUB_TOKEN"])
    raise typer.Exit(1 if res["verdict"] == "FAIL" else 0)


@app.command("bisect")
def bisect_cmd(config: str = "bisectr.yaml",
               good: str = typer.Option(...), bad: str = typer.Option(...),
               post: bool = False):
    """Find the first bad commit between good and bad."""
    cfg = load(config)
    good = subprocess.check_output(["git", "rev-parse", good], text=True).strip()
    bad = subprocess.check_output(["git", "rev-parse", bad], text=True).strip()
    mid = subprocess.check_output(
        ["git", "rev-list", "--reverse", "--ancestry-path", f"{good}..{bad}"], text=True).split()
    shas = [good] + [s for s in mid if probe.image_exists(cfg, s)]   # no image = git bisect skip
    if not probe.image_exists(cfg, good) or shas[-1] != bad:
        typer.echo("good and bad commits must both have an image in ECR")
        raise typer.Exit(2)
    targets = [(_image(cfg, s), {}) for s in shas]
    result, evidence = run_bisect(cfg, targets)
    md = report.bisect_markdown(result, shas, evidence)
    typer.echo(md)
    store.save_run("bisect", {"kind": result.kind, "culprit": result.culprit,
                              "window": result.window, "evidence": evidence})
    if post and result.kind == "found":
        url = report.open_issue(os.environ["GITHUB_REPOSITORY"],
                                f"Performance regression: {shas[result.culprit][:10]}", md,
                                os.environ["GITHUB_TOKEN"])
        typer.echo(url)


@app.command("eval")
def eval_cmd(scenarios: str = "eval/scenarios.yaml", image: str = typer.Option(...),
             trials: int = 5, bisect_trials: int = 3, out: str = "eval/results.csv",
             config: str = "bisectr.yaml"):
    """Run the evaluation harness."""
    subprocess.run([sys.executable, "eval/run_eval.py", "--config", config, "--scenarios", scenarios,
                    "--image", image, "--trials", str(trials), "--bisect-trials", str(bisect_trials),
                    "--out", out], check=True)
