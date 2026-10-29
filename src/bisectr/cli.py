from __future__ import annotations
import csv, json, os, subprocess, sys, time
import uuid
from datetime import datetime, timezone
from typing import List, Optional
import typer

from . import probe, report, store
from .bisect import run_bisect
from .config import load
from .gate import run_gate
from .guardrails import GuardrailBlocked

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _kv(items):
    return dict(i.split("=", 1) for i in (items or []))


def _image(cfg, ref):
    return ref if ":" in ref else f"{cfg.infra.image_repo}:{ref}"


def _resolve_commit(ref, label):
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError:
        typer.echo(
            f"Invalid {label} commit '{ref}'. Pass an existing commit SHA or ref; "
            "use `git --no-pager log --oneline` to find commit SHAs.",
            err=True,
        )
        raise typer.Exit(2)


def _auto_baseline(cfg, branch):
    shas = subprocess.check_output(["git", "rev-list", branch, "-n", "50"], text=True).split()
    for s in shas:
        if probe.image_exists(cfg, s):
            return s
    typer.echo("no commit on the main branch has an image in ECR")
    raise typer.Exit(2)


def _bisect_result_payload(result, shas, evidence):
    return {
        "kind": result.kind,
        "culprit": shas[result.culprit] if result.culprit is not None else None,
        "window": (
            [shas[result.window[0]], shas[result.window[1]]]
            if result.window is not None else None
        ),
        "probes": result.probes,
        "evidence": evidence,
    }


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
    pr_head_sha = None
    if post and pr:
        pr_data = report.validate_pr(
            os.environ["GITHUB_REPOSITORY"], pr, os.environ["GITHUB_TOKEN"])
        pr_head_sha = pr_data["head"]["sha"]
    if baseline == "auto":
        baseline = _auto_baseline(cfg, main_branch)
    for ref in (candidate, baseline):
        if ":" not in ref and not probe.image_exists(cfg, ref):
            typer.echo(f"No image tagged {ref} in ECR. Commit your changes, then run ./scripts/push_images.sh "
                       f"(it pushes an image for the current HEAD).")
            raise typer.Exit(2)
    try:
        res = run_gate(cfg, (_image(cfg, candidate), _kv(cand_env)),
                       (_image(cfg, baseline), _kv(base_env)), use_cache=not no_cache)
    except GuardrailBlocked as exc:
        message = f"Bisectr run blocked: {exc}"
        typer.echo(message, err=True)
        if post and pr:
            report.post_pr_comment(
                os.environ["GITHUB_REPOSITORY"], pr, message, os.environ["GITHUB_TOKEN"])
            report.post_check_run(
                os.environ["GITHUB_REPOSITORY"], pr_head_sha, "Bisectr blocked", "failure",
                message, os.environ["GITHUB_TOKEN"],
            )
        raise typer.Exit(2)
    md = report.comment_markdown(res, cfg)
    typer.echo(md)
    run_id = uuid.uuid4().hex
    run_data = {
        "inputs": {
            "candidate": candidate,
            "baseline": baseline,
            "task": cfg.task.model_dump(),
            "scenario": cfg.scenario.model_dump(),
            "thresholds": cfg.thresholds.model_dump(),
            "cost": cfg.cost.model_dump(),
            "pricing": cfg.pricing.model_dump(),
            "replicas": cfg.replicas,
        },
        "result": res,
    }
    store.save_run("gate", run_data, cfg, run_id)
    report_uri = store.save_report(cfg, run_id, report.html_report("Bisectr gate", md, run_data))
    typer.echo(f"HTML report: {report_uri}")
    if post and pr:
        report.post_pr_comment(os.environ["GITHUB_REPOSITORY"], pr, md, os.environ["GITHUB_TOKEN"])
        conclusion = {"PASS": "success", "WARN": "neutral", "FAIL": "failure"}[res["verdict"]]
        report.post_check_run(
            os.environ["GITHUB_REPOSITORY"], pr_head_sha, res["verdict"], conclusion, md,
            os.environ["GITHUB_TOKEN"],
        )
    raise typer.Exit(1 if res["verdict"] == "FAIL" else 0)


@app.command()
def suite(config: str = "bisectr.yaml",
          candidate: str = typer.Option(...),
          baseline: str = "auto",
          main_branch: str = "origin/main",
          profiles: Optional[List[str]] = typer.Option(None, "--profile"),
          no_cache: bool = False):
    """Run the gate for several configured workload profiles in one command."""
    cfg = load(config)
    selected = cfg.scenarios or [cfg.scenario]
    if profiles:
        missing = sorted(set(profiles) - {scenario.profile for scenario in selected})
        if missing:
            raise typer.BadParameter(f"unknown scenario profile(s): {', '.join(missing)}")
        selected = [scenario for scenario in selected if scenario.profile in profiles]
    if baseline == "auto":
        baseline = _auto_baseline(cfg, main_branch)
    for ref in (candidate, baseline):
        if ":" not in ref and not probe.image_exists(cfg, ref):
            typer.echo(f"No image tagged {ref} in ECR.", err=True)
            raise typer.Exit(2)

    results = []
    sections = []
    for scenario in selected:
        scenario_cfg = cfg.model_copy(update={"scenario": scenario})
        try:
            result = run_gate(
                scenario_cfg, (_image(cfg, candidate), {}),
                (_image(cfg, baseline), {}), use_cache=not no_cache,
            )
        except GuardrailBlocked as exc:
            typer.echo(f"Bisectr suite blocked on profile '{scenario.profile}': {exc}", err=True)
            raise typer.Exit(2)
        results.append({"profile": scenario.profile, "result": result})
        sections.extend([f"## Workload profile: {scenario.profile}", "",
                         report.comment_markdown(result, scenario_cfg), ""])

    overall = (
        "FAIL" if any(item["result"]["verdict"] == "FAIL" for item in results)
        else "WARN" if any(item["result"]["verdict"] == "WARN" for item in results)
        else "PASS"
    )
    markdown = (
        f"### Bisectr workload suite: {overall}\n\n"
        + "\n".join(f"- **{item['profile']}**: {item['result']['verdict']}" for item in results)
        + "\n\n"
        + "\n".join(sections)
    )
    typer.echo(markdown)
    run_id = uuid.uuid4().hex
    data = {
        "inputs": {
            "candidate": candidate,
            "baseline": baseline,
            "profiles": [scenario.profile for scenario in selected],
        },
        "result": {"verdict": overall, "scenarios": results},
    }
    store.save_run("suite", data, cfg, run_id)
    report_uri = store.save_report(cfg, run_id, report.html_report("Bisectr workload suite", markdown, data))
    typer.echo(f"HTML report: {report_uri}")
    raise typer.Exit(1 if overall == "FAIL" else 0)


@app.command("bisect")
def bisect_cmd(config: str = "bisectr.yaml",
               good: str = typer.Option(...), bad: str = typer.Option(...),
               post: bool = False, result_json: Optional[str] = None):
    """Find the first bad commit between good and bad."""
    cfg = load(config)
    good = _resolve_commit(good, "good")
    bad = _resolve_commit(bad, "bad")
    if good == bad:
        typer.echo("good and bad commits must be different", err=True)
        raise typer.Exit(2)
    if subprocess.run(["git", "merge-base", "--is-ancestor", good, bad],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        typer.echo("good commit must be an ancestor of bad commit", err=True)
        raise typer.Exit(2)
    mid = subprocess.check_output(
        ["git", "rev-list", "--reverse", "--ancestry-path", f"{good}..{bad}"], text=True).split()
    shas = [good] + [s for s in mid if probe.image_exists(cfg, s)]   # no image = git bisect skip
    if not probe.image_exists(cfg, good) or bad not in shas:
        typer.echo("good and bad commits must both have an image in ECR")
        raise typer.Exit(2)
    targets = [(_image(cfg, s), {}) for s in shas]
    try:
        result, evidence = run_bisect(cfg, targets)
    except GuardrailBlocked as exc:
        typer.echo(f"Bisectr run blocked: {exc}", err=True)
        raise typer.Exit(2)
    md = report.bisect_markdown(result, shas, evidence)
    typer.echo(md)
    run_id = uuid.uuid4().hex
    relevant_indices = {0, len(shas) - 1}
    relevant_indices.update(item["index"] for item in evidence)
    if result.culprit is not None:
        relevant_indices.add(result.culprit)
    if result.window is not None:
        relevant_indices.update(result.window)
    run_data = {
        "inputs": {
            "good": good,
            "bad": bad,
            "commit_count": len(shas),
            "measured_commit_shas": {
                str(index): shas[index] for index in sorted(relevant_indices)
            },
            "scenario": cfg.scenario.model_dump(),
            "thresholds": cfg.thresholds.model_dump(),
        },
        "result": {"kind": result.kind, "culprit": result.culprit, "window": result.window,
                   "probes": result.probes, "evidence": evidence},
    }
    if result_json:
        with open(result_json, "w", encoding="utf-8") as output:
            json.dump(_bisect_result_payload(result, shas, evidence), output, indent=2)
            output.write("\n")
    store.save_run("bisect", run_data, cfg, run_id)
    report_uri = store.save_report(
        cfg, run_id, report.html_report("Bisectr bisect", md, run_data))
    typer.echo(f"HTML report: {report_uri}")
    if post and result.kind == "found":
        url = report.open_issue(os.environ["GITHUB_REPOSITORY"],
                                f"Performance regression: {shas[result.culprit][:10]}", md,
                                os.environ["GITHUB_TOKEN"])
        typer.echo(url)


@app.command("eval")
def eval_cmd(scenarios: str = "eval/scenarios.yaml", image: str = typer.Option(...),
             trials: int = 5, bisect_trials: int = 3, out: str = "eval/results.csv",
             config: str = "bisectr.yaml", seed: int = 20261029, resume: bool = False):
    """Run the evaluation harness."""
    command = [
        sys.executable, "eval/run_eval.py", "--config", config, "--scenarios", scenarios,
        "--image", image, "--trials", str(trials), "--bisect-trials", str(bisect_trials),
        "--seed", str(seed), "--out", out,
    ]
    if resume:
        command.append("--resume")
    subprocess.run(command, check=True)


@app.command("validate")
def validate_cmd(config: str = "bisectr.yaml",
                 baseline: str = typer.Option(...),
                 candidate: str = typer.Option(...),
                 trials: int = 5,
                 out: str = "eval/validation.csv"):
    """Repeat an A/B gate on two images and save the measurements as CSV."""
    if trials <= 0:
        raise typer.BadParameter("trials must be greater than zero")
    cfg = load(config)
    for label, image in (("baseline", baseline), ("candidate", candidate)):
        if ":" not in image and not probe.image_exists(cfg, image):
            typer.echo(f"No ECR image found for {label} tag '{image}'.", err=True)
            raise typer.Exit(2)
    baseline_image, candidate_image = _image(cfg, baseline), _image(cfg, candidate)
    rows = []
    for trial in range(1, trials + 1):
        started = time.monotonic()
        try:
            result = run_gate(
                cfg, (candidate_image, {}), (baseline_image, {}), use_cache=False
            )
        except GuardrailBlocked as exc:
            typer.echo(f"Validation run blocked: {exc}", err=True)
            raise typer.Exit(2)
        elapsed = round(time.monotonic() - started, 2)
        detail = result["detail"]
        row = {
            "trial": trial,
            "profile": cfg.scenario.profile,
            "baseline": baseline,
            "candidate": candidate,
            "verdict": result["verdict"],
            "p95_ratio": detail["ratio"],
            "p_value": detail["p"],
            "replicas_worse": detail["agree"],
            "cost_regression": result["cost"]["regression"],
            "wall_seconds": elapsed,
        }
        rows.append(row)
        run_data = {
            "inputs": {
                "baseline": baseline,
                "candidate": candidate,
                "trial": trial,
                "scenario": cfg.scenario.model_dump(),
                "thresholds": cfg.thresholds.model_dump(),
            },
            "result": result,
        }
        store.save_run("validate", run_data, cfg)
        typer.echo(
            f"Trial {trial}/{trials}: {result['verdict']} "
            f"(p95 ratio {detail['ratio']:.2f}x, p={detail['p']:.3g})"
        )

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    typer.echo(f"Validation results: {out}")


@app.command("verify-fix")
def verify_fix(config: str = "bisectr.yaml",
               baseline: str = typer.Option(..., help="Known-good image tag or commit SHA"),
               candidate: str = typer.Option(..., help="Fixed candidate image tag or commit SHA")):
    """Verify that a fix restores performance relative to a known-good baseline."""
    cfg = load(config)
    for label, ref in (("baseline", baseline), ("candidate", candidate)):
        if ":" not in ref and not probe.image_exists(cfg, ref):
            typer.echo(f"No ECR image found for {label} tag '{ref}'.", err=True)
            raise typer.Exit(2)
    try:
        result = run_gate(
            cfg, (_image(cfg, candidate), {}), (_image(cfg, baseline), {}),
            use_cache=False,
        )
    except GuardrailBlocked as exc:
        typer.echo(f"Fix verification blocked: {exc}", err=True)
        raise typer.Exit(2)

    run_id = uuid.uuid4().hex
    data = {
        "inputs": {
            "baseline": baseline,
            "candidate": candidate,
            "scenario": cfg.scenario.model_dump(),
            "thresholds": cfg.thresholds.model_dump(),
        },
        "result": result,
    }
    store.save_run("verify-fix", data, cfg, run_id)
    markdown = report.comment_markdown(result, cfg)
    report_uri = store.save_report(
        cfg, run_id, report.html_report("Bisectr fix verification", markdown, data)
    )
    if result["verdict"] == "PASS":
        typer.echo(f"Regression resolved: {candidate} passed against known-good {baseline}.")
    else:
        typer.echo(
            f"Regression not confirmed as resolved: verification returned "
            f"{result['verdict']} ({', '.join(result['reasons']) or 'inconclusive'})."
        )
    typer.echo(markdown)
    typer.echo(f"HTML report: {report_uri}")
    raise typer.Exit(0 if result["verdict"] == "PASS" else 1)


@app.command()
def trends(config: str = "bisectr.yaml", kind: str = "all", limit: int = 20):
    """Show recent gate, validation, bisect, and fix-verification results."""
    if kind not in {"all", "gate", "bisect", "validate", "verify-fix"}:
        raise typer.BadParameter("kind must be all, gate, bisect, validate, or verify-fix")
    if limit <= 0:
        raise typer.BadParameter("limit must be greater than zero")
    cfg = load(config)
    runs = store.list_runs(cfg, kind=None if kind == "all" else kind, limit=limit)
    if not runs:
        typer.echo("No run history found.")
        return

    typer.echo("Date (UTC)           Kind    Profile       Outcome         p95 ratio")
    for run in runs:
        data = run["data"]
        inputs = data.get("inputs", {})
        result = data.get("result", {})
        scenario = inputs.get("scenario", {})
        profile = scenario.get("profile", "default")
        if run["kind"] in {"gate", "validate", "verify-fix"}:
            outcome = result.get("verdict", "unknown")
            ratio = result.get("detail", {}).get("ratio")
        elif run["kind"] == "suite":
            outcome = result.get("verdict", "unknown")
            profile = f"{len(result.get('scenarios', []))} profiles"
            ratio = None
        else:
            outcome = result.get("kind", "unknown")
            ratio = None
        ratio_text = f"{ratio:.2f}x" if isinstance(ratio, (int, float)) else "-"
        timestamp = datetime.fromtimestamp(run["created_at"], timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        typer.echo(
            f"{timestamp:<20} {run['kind']:<7} {profile[:13]:<13} "
            f"{outcome[:15]:<15} {ratio_text}"
        )


@app.command()
def dashboard(config: str = "bisectr.yaml", out: str = "runs/dashboard.html", limit: int = 100):
    """Write a local HTML dashboard from stored run history."""
    if limit <= 0:
        raise typer.BadParameter("limit must be greater than zero")
    cfg = load(config)
    runs = store.list_runs(cfg, limit=limit)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as file:
        file.write(report.history_dashboard(runs))
    typer.echo(f"Dashboard written to {out} ({len(runs)} runs).")
