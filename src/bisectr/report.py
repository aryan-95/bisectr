from __future__ import annotations
import html
import json
import httpx

MARKER = "<!-- bisectr -->"
ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}


def _pct(b, c):
    if not b:
        return "n/a"
    d = (c - b) / b * 100
    return "none" if abs(d) < 0.5 else f"{d:+.0f}%"


def comment_markdown(res: dict, cfg) -> str:
    b, c, d, cost = res["base"], res["cand"], res["detail"], res["cost"]
    rows = [
        ("p95 latency", f"{b['p95']:.0f} ms", f"{c['p95']:.0f} ms", _pct(b["p95"], c["p95"])),
        ("Error rate", f"{b['err']*100:.1f}%", f"{c['err']*100:.1f}%",
         "none" if abs(c["err"] - b["err"]) < 0.001 else f"{(c['err']-b['err'])*100:+.1f} pp"),
    ]
    if b["cpu_per_1000"] and c["cpu_per_1000"]:
        rows.append(("CPU per 1,000 requests", f"{b['cpu_per_1000']:.2f} CPU-s",
                     f"{c['cpu_per_1000']:.2f} CPU-s", _pct(b["cpu_per_1000"], c["cpu_per_1000"])))
    rows.append(("Peak memory", f"{b['mem_mb']:.0f} MB", f"{c['mem_mb']:.0f} MB", _pct(b["mem_mb"], c["mem_mb"])))

    out = [MARKER, f"### Bisectr: {ICON[res['verdict']]} {res['verdict']}", "",
           "| Metric | main (baseline) | This PR | Change |", "|---|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows]
    why = f" ({', '.join(res['reasons'])})" if res["reasons"] else ""
    out += ["", f"**Verdict: {res['verdict']}{why}.** Mann-Whitney p = {d['p']:.3g}, "
            f"p95 ratio {d['ratio']:.2f}, {d['agree']} of {res['replicas']} replicas worse than baseline."
            + (" Re-probed once with a longer run." if res["reprobed"] else "")]
    out += ["", f"Workload profile: `{cfg.scenario.profile}` "
            f"({cfg.scenario.rps} RPS, {cfg.scenario.seconds}s, "
            f"{len(cfg.scenario.endpoints)} endpoint mix)."]
    if "latency" in res["reasons"] or "errors" in res["reasons"]:
        out.append(
            f"Review the candidate's latency/error changes against the configured "
            f"p95 ratio threshold ({cfg.thresholds.min_ratio:.2f}x) and replica agreement "
            f"({cfg.thresholds.min_agree} of {res['replicas']})."
        )
    elif "cost" in res["reasons"]:
        out.append(
            f"Measured CPU-seconds per request crossed the configured "
            f"{cfg.thresholds.cost_min_ratio:.2f}x cost threshold; review the sizing estimate below."
        )
    elif res["verdict"] == "WARN":
        out.append(
            "The measurements were inconclusive or the cost estimate crossed its warning "
            "threshold; inspect the run report and consider rerunning with a longer scenario."
        )
    else:
        out.append("No configured latency, error-rate, or cost regression threshold was exceeded.")
    if cost.get("available"):
        line = f"Sizing estimate at {cfg.cost.target_rps} RPS: {cost['tasks_base']} → {cost['tasks_cand']} tasks"
        line += (f", {cost['delta']:+.2f} USD per month (from your pricing config)." if cost["priced"]
                 else ". Set `pricing` in bisectr.yaml for a dollar figure.")
        if cost["needs_bigger_task"]:
            line += " Peak memory is above 80% of the task size."
        out += ["", line]
    return "\n".join(out)


def html_report(title: str, markdown: str, data: dict) -> str:
    rendered_data = json.dumps(data, indent=2, default=_json_default)
    chart = _latency_quantiles_html(data)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ color: #1f2937; font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 960px; padding: 0 1rem; }}
    pre {{ background: #f3f4f6; border-radius: .5rem; overflow-x: auto; padding: 1rem; white-space: pre-wrap; }}
    details {{ margin-top: 2rem; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <pre>{html.escape(markdown)}</pre>
  {chart}
  <details><summary>Run data</summary><pre>{html.escape(rendered_data)}</pre></details>
</body>
</html>
"""


def _latency_quantiles_html(data):
    result = data.get("result", {})
    baseline = result.get("base", {}).get("latency_quantiles_ms")
    candidate = result.get("cand", {}).get("latency_quantiles_ms")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return ""
    percentiles = ("p50", "p90", "p95", "p99")
    values = [float(series[key]) for series in (baseline, candidate) for key in percentiles]
    maximum = max(values, default=0.0)
    scale = 600 / maximum if maximum > 0 else 0
    rows = []
    for index, percentile in enumerate(percentiles):
        y = 36 + index * 48
        base_value = float(baseline[percentile])
        candidate_value = float(candidate[percentile])
        rows.append(
            f'<text x="0" y="{y + 12}">{percentile}</text>'
            f'<rect x="48" y="{y}" width="{base_value * scale:.1f}" height="14" fill="#2563eb">'
            f'<title>Baseline {base_value:.2f} ms</title></rect>'
            f'<rect x="48" y="{y + 17}" width="{candidate_value * scale:.1f}" height="14" fill="#dc2626">'
            f'<title>Candidate {candidate_value:.2f} ms</title></rect>'
        )
    return (
        '<section><h2>Latency distribution</h2>'
        '<p>Baseline (blue) and candidate (red), percentile latency in milliseconds.</p>'
        '<svg role="img" aria-label="Latency percentile comparison" viewBox="0 0 700 230" '
        'style="max-width:100%;height:auto">'
        + "".join(rows)
        + '</svg><p><span style="color:#2563eb">Baseline</span> · '
        '<span style="color:#dc2626">Candidate</span></p></section>'
    )


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _h(token):
    return {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}


def validate_pr(repo, pr, token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr}"
    response = httpx.get(url, headers=_h(token), timeout=30.0)
    if response.status_code == 404:
        raise RuntimeError(
            f"GitHub could not find pull request #{pr} in {repo}. "
            "Check the repository and pull request number, and confirm the token can access the repository."
        )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("head"), dict) or not data["head"].get("sha"):
        raise RuntimeError(f"Unexpected GitHub API response when reading pull request #{pr} in {repo}.")
    return data


def post_check_run(repo, head_sha, title, conclusion, summary, token):
    response = httpx.post(
        f"https://api.github.com/repos/{repo}/check-runs",
        headers=_h(token),
        json={
            "name": "Bisectr performance gate",
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary[:65_000]},
        },
        timeout=30.0,
    )
    response.raise_for_status()


def post_pr_comment(repo, pr, body, token):
    base = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"

    response = httpx.get(
        base,
        headers=_h(token),
        params={"per_page": 100},
        timeout=30.0,
    )
    response.raise_for_status()

    existing = response.json()

    if not isinstance(existing, list):
        raise RuntimeError(
            f"Unexpected GitHub API response when listing PR comments: "
            f"{existing}"
        )

    mine = next(
        (
            comment
            for comment in existing
            if isinstance(comment, dict)
            and MARKER in comment.get("body", "")
        ),
        None,
    )

    if mine:
        response = httpx.patch(
            f"https://api.github.com/repos/{repo}/issues/comments/{mine['id']}",
            headers=_h(token),
            json={"body": body},
            timeout=30.0,
        )
    else:
        response = httpx.post(
            base,
            headers=_h(token),
            json={"body": body},
            timeout=30.0,
        )

    response.raise_for_status()


def open_issue(repo, title, body, token):
    r = httpx.post(f"https://api.github.com/repos/{repo}/issues", headers=_h(token),
                   json={"title": title, "body": body})
    r.raise_for_status()
    return r.json()["html_url"]


def bisect_markdown(result, shas, evidence) -> str:
    if result.kind == "found":
        head = f"**Culprit: `{shas[result.culprit]}`** (parent `{shas[result.culprit-1]}` measured good, verified with 2x samples)."
    elif result.kind in ("ambiguous", "flaky"):
        lo, hi = result.window
        head = f"**{result.kind.upper()}.** Suspect window: `{shas[lo]}` (good) .. `{shas[hi]}` (bad). No confident culprit."
    else:
        head = "**Regression not reproducible under this scenario.**"
    rows = ["| commit | verdict | p95 ratio | p | replicas worse |", "|---|---|---|---|---|"]
    for e in evidence:
        c10 = shas[e["index"]][:10]
        who = f"`{c10}` vs parent" if "pair_vs" in e else (f"`{c10}` recheck vs fresh baseline" if e.get("recheck") else f"`{c10}`")
        rows.append(f"| {who} | {e['verdict']} | {e['ratio']:.2f} | {e['p']:.3g} | {e['agree']} |")
    return f"### Bisectr bisect result\n\n{head}\n\nProbes used: {result.probes}\n\n" + "\n".join(rows)
