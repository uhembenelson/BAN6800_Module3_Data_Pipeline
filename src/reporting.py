"""Charts for the run artefacts and the presentation.

Every figure is generated from the actual run outputs - no hand-drawn numbers.
The palette matches the deck so the visuals read as one system.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / ".mplcache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

NAVY = "#0F2A47"
TEAL = "#1F8A9C"
AMBER = "#E4A11B"
RED = "#B03A2E"
GREY = "#6B7280"
LIGHT = "#EDF1F6"

plt.rcParams.update(
    {
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.edgecolor": "#CBD5E1",
        "axes.labelcolor": NAVY,
        "text.color": NAVY,
        "xtick.color": GREY,
        "ytick.color": GREY,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
    }
)


def _save(fig: matplotlib.figure.Figure, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def stage_funnel(counts: list[tuple[str, int]], path: Path) -> str:
    """Horizontal bar chart of record counts through the pipeline."""
    labels = [name for name, _ in counts]
    values = [value for _, value in counts]
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    colours = [NAVY if index == 0 else TEAL for index in range(len(values))]
    bars = ax.barh(labels[::-1], values[::-1], color=colours[::-1], height=0.62)
    ax.set_xlabel("records")
    ax.set_xlim(0, max(values) * 1.16)
    for bar, value in zip(bars, values[::-1]):
        ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2, f"{value:,}",
                va="center", fontsize=9, color=NAVY, fontweight="bold")
    ax.grid(axis="x", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


def validation_gate(interim: dict[str, Any], gold: dict[str, Any], path: Path) -> str:
    """Grouped bars: expectations passed vs failed at each gate."""
    fig, ax = plt.subplots(figsize=(5.6, 2.9))
    gates = ["Gate A\ninterim", "Gate B\ngold"]
    passed = [interim["expectations_passed"], gold["expectations_passed"]]
    failed = [interim["expectations_failed"], gold["expectations_failed"]]
    x = np.arange(len(gates))
    width = 0.42
    ax.bar(x - width / 2, passed, width, label="passed", color=TEAL)
    ax.bar(x + width / 2, failed, width, label="failed", color=RED)
    ax.set_xticks(x)
    ax.set_xticklabels(gates)
    ax.set_ylabel("expectations")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.set_ylim(0, max(max(passed), max(failed)) + 3)
    for index, (p, f) in enumerate(zip(passed, failed)):
        ax.text(index - width / 2, p + 0.5, str(p), ha="center", fontsize=9, color=TEAL, fontweight="bold")
        ax.text(index + width / 2, f + 0.5, str(f), ha="center", fontsize=9, color=RED, fontweight="bold")
    ax.grid(axis="y", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


def bias_selection_rates(summary: pd.DataFrame, attribute: str, decision: str, path: Path) -> str:
    """Selection rate per group for one attribute/decision pair."""
    subset = summary[(summary["protected_attribute"] == attribute) & (summary["decision"] == decision)]
    subset = subset.sort_values("selection_rate", ascending=True)
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    colours = []
    for _, row in subset.iterrows():
        if not row["sample_sufficient"]:
            colours.append(GREY)
        elif row["within_threshold"] is False:
            colours.append(RED)
        else:
            colours.append(TEAL)
    bars = ax.barh(subset["group"].astype(str), subset["selection_rate"], color=colours, height=0.6)
    ax.set_xlabel("share of group selected")
    ax.set_xlim(0, min(1.0, float(subset["selection_rate"].max()) * 1.35))
    for bar, rate, count in zip(bars, subset["selection_rate"], subset["population_records"]):
        ax.text(bar.get_width() * 1.02, bar.get_y() + bar.get_height() / 2,
                f"{rate:.1%}  (n={count:,})", va="center", fontsize=8, color=NAVY)
    ax.grid(axis="x", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


def region_mix(gold: pd.DataFrame, path: Path) -> str:
    """Population share versus high-value share, by region."""
    base = gold["region"].value_counts(normalize=True)
    selected = gold.loc[gold["high_value_flag"], "region"].value_counts(normalize=True)
    order = base.sort_values(ascending=True).index
    fig, ax = plt.subplots(figsize=(5.4, 2.8))
    y = np.arange(len(order))
    ax.barh(y + 0.19, base.reindex(order), height=0.36, label="population", color=NAVY)
    ax.barh(y - 0.19, selected.reindex(order), height=0.36, label="high value", color=AMBER)
    ax.set_yticks(y)
    ax.set_yticklabels(order)
    ax.set_xlabel("share of records")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="x", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


def balance_distribution(gold: pd.DataFrame, threshold: float, path: Path) -> str:
    """Balance histogram with the high-value cut-off marked."""
    fig, ax = plt.subplots(figsize=(5.4, 2.8))
    ax.hist(gold["balance"], bins=40, color=TEAL, alpha=0.85, edgecolor="white", linewidth=0.4)
    ax.axvline(threshold, color=AMBER, linewidth=1.8, linestyle="--")
    ax.text(threshold, ax.get_ylim()[1] * 0.92, f"  high-value cut-off\n  GBP {threshold:,.0f}",
            color=AMBER, fontsize=8, va="top")
    ax.set_xlabel("balance (GBP)")
    ax.set_ylabel("customers")
    ax.grid(axis="y", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


#: Short human labels for the cleaning chart - the rule descriptions are too long
#: to use as axis labels without truncating them mid-word.
RULE_LABELS = {
    "CQ-01": "duplicate records removed",
    "CQ-02": "duplicate keys collapsed",
    "CQ-03": "impossible ages rejected",
    "CQ-04": "missing ages imputed",
    "CQ-05": "non-positive balances",
    "CQ-06": "missing balances imputed",
    "CQ-07": "outliers flagged",
    "CQ-08": "job codes set to Unknown",
    "CQ-09": "missing demographics",
    "CQ-10": "bad dates dropped",
}


def cleaning_effects(summary: dict[str, Any], path: Path) -> str:
    """Bar chart of defects handled per cleaning rule."""
    rules = summary["rules"]
    rules = [rule for rule in rules if rule["records_affected"] > 0]
    if not rules:
        rules = summary["rules"][:1]
    labels = [
        f"{rule['rule']}  {RULE_LABELS.get(rule['rule'], rule['description'][:28])}"
        for rule in rules
    ]
    values = [rule["records_affected"] for rule in rules]
    fig, ax = plt.subplots(figsize=(7.2, max(2.2, 0.46 * len(labels) + 1.0)))
    bars = ax.barh(labels[::-1], values[::-1], color=TEAL, height=0.6)
    ax.set_xlabel("records affected")
    ax.set_xlim(0, max(values) * 1.2)
    for bar, value in zip(bars, values[::-1]):
        ax.text(bar.get_width() * 1.02, bar.get_y() + bar.get_height() / 2, f"{value:,}",
                va="center", fontsize=8, color=NAVY)
    ax.grid(axis="x", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


def privacy_tradeoff(report: dict[str, Any], path: Path) -> str:
    """k-anonymity achieved at each candidate release granularity."""
    scenarios = report["granularity_analysis"]["scenarios"]
    threshold = report["granularity_analysis"]["threshold"]
    names = [name.replace("_", " ") for name in scenarios]
    values = [item.get("k_anonymity", 0) for item in scenarios.values()]
    colours = [TEAL if value >= threshold else RED for value in values]

    fig, ax = plt.subplots(figsize=(6.4, 2.7))
    bars = ax.bar(names, values, color=colours, width=0.55)
    ax.set_yscale("log")
    ax.axhline(threshold, color=AMBER, linestyle="--", linewidth=1.4)
    ax.text(len(names) - 0.55, threshold * 1.25, f"release threshold k={threshold}",
            ha="right", fontsize=8, color=AMBER)
    ax.set_ylabel("k-anonymity (log scale)")
    ax.set_ylim(0.8, max(values) * 3)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value * 1.18, f"k={value}",
                ha="center", fontsize=8, color=NAVY, fontweight="bold")
    ax.tick_params(axis="x", labelrotation=0, labelsize=7)
    ax.grid(axis="y", color=LIGHT, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, path)


def produce_all(
    figures_dir: Path,
    *,
    funnel: list[tuple[str, int]],
    interim_validation: dict[str, Any],
    gold_validation: dict[str, Any],
    bias_summary: pd.DataFrame,
    gold: pd.DataFrame,
    threshold: float,
    cleaning_summary: dict[str, Any],
    privacy: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Render the full chart set for the run."""
    outputs = {
        "funnel": stage_funnel(funnel, figures_dir / "stage_funnel.png"),
        "validation": validation_gate(interim_validation, gold_validation, figures_dir / "validation_gates.png"),
        "region_mix": region_mix(gold, figures_dir / "region_mix.png"),
        "balance": balance_distribution(gold, threshold, figures_dir / "balance_distribution.png"),
        "cleaning": cleaning_effects(cleaning_summary, figures_dir / "cleaning_effects.png"),
    }
    if privacy:
        outputs["privacy"] = privacy_tradeoff(privacy, figures_dir / "privacy_tradeoff.png")
    for attribute in ("gender", "region", "age_band"):
        if (bias_summary["protected_attribute"] == attribute).any():
            key = f"bias_{attribute}"
            outputs[key] = bias_selection_rates(
                bias_summary, attribute, "high_value_flag", figures_dir / f"{key}.png"
            )
    return outputs
