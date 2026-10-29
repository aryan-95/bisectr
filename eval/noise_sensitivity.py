"""Measure bisect outcomes as oracle verdicts are independently flipped by noise."""
from __future__ import annotations

import argparse
import csv
import random

from bisectr.bisect import search


def simulate(flip_rates, trials=1000, commits=16, seed=20261029):
    if trials <= 0 or commits < 2:
        raise ValueError("trials must be positive and commits must be at least 2")
    if any(not 0 <= rate <= 1 for rate in flip_rates):
        raise ValueError("flip rates must be between zero and one")

    rng = random.Random(seed)
    rows = []
    for rate in flip_rates:
        counts = {
            "exact": 0,
            "wrong": 0,
            "ambiguous": 0,
            "flaky": 0,
            "not_reproducible": 0,
        }
        for _ in range(trials):
            culprit = rng.randrange(1, commits)

            def label(index):
                bad = index >= culprit
                return ("good" if bad else "bad") if rng.random() < rate else (
                    "bad" if bad else "good"
                )

            def oracle(indices, confirm=False):
                return {index: label(index) for index in indices}

            def pair(lo, hi):
                votes = sum(label(hi) == "bad" for _ in range(3))
                return "bad" if votes >= 2 else "inconclusive"

            result = search(commits, oracle, k=3, max_probes=64, pair=pair)
            if result.kind == "found":
                counts["exact" if result.culprit == culprit else "wrong"] += 1
            else:
                counts[result.kind] += 1

        rows.append({
            "flip_rate": rate,
            "trials": trials,
            **counts,
            "exact_rate": counts["exact"] / trials,
            "wrong_rate": counts["wrong"] / trials,
            "safe_undecided_rate": (
                counts["ambiguous"] + counts["flaky"] + counts["not_reproducible"]
            ) / trials,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--commits", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--flip-rates", default="0,0.01,0.05,0.1,0.2")
    parser.add_argument("--out", default="eval/noise-sensitivity.csv")
    args = parser.parse_args()
    rates = [float(value) for value in args.flip_rates.split(",")]
    rows = simulate(rates, args.trials, args.commits, args.seed)
    with open(args.out, "w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("flip_rate | exact | wrong | safe undecided")
    for row in rows:
        print(
            f"{row['flip_rate']:.0%} | {row['exact_rate']:.1%} | "
            f"{row['wrong_rate']:.1%} | {row['safe_undecided_rate']:.1%}"
        )
    print(f"CSV: {args.out}")


if __name__ == "__main__":
    main()
