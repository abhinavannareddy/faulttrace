"""Draws the figures used in the README from the vehicle configs and results/latest.json.

Needs matplotlib (see requirements-dev.txt):  python tools/make_figures.py
"""
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from faulttrace.model import load_vehicle

OUT = ROOT / "docs"
INK, MUTED, GRID = "#1f2933", "#6b7785", "#e4e7eb"
PALETTE = ["#2f6fdb", "#e07a1f", "#2a9d8f", "#b5476b", "#7a5cc7", "#8a9a2b", "#c9a227", "#4b8bbe", "#5d6d7e", "#d1495b", "#00798c"]
plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.edgecolor": GRID})


def fault_graph(name="truck", root="power_dist"):
    v = load_vehicle(name)
    g = v.graph
    systems = sorted({d["system"] for _, d in g.nodes(data=True)})
    color = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(systems)}
    # layer = longest path from any source, so every arrow points left to right
    dag = nx.DiGraph(g)
    while not nx.is_directed_acyclic_graph(dag):
        dag.remove_edge(*nx.find_cycle(dag)[0][:2])
    layer = {}
    for gen, nodes in enumerate(nx.topological_generations(dag)):
        for n in nodes:
            layer[n] = gen
    cols = {}
    for n in sorted(g.nodes, key=lambda n: (layer[n], g.nodes[n]["system"], n)):
        cols.setdefault(layer[n], []).append(n)
    pos = {}
    tallest = max(len(c) for c in cols.values())
    for x, nodes in cols.items():
        for i, n in enumerate(nodes):
            pos[n] = (x * 2.2, -(i - (len(nodes) - 1) / 2) * 1.0 * tallest / max(len(nodes), 1) ** 0.0)

    fig, ax = plt.subplots(figsize=(13, 0.62 * tallest + 2.6))
    reach = nx.descendants(g, root) | {root}
    for a, b in g.edges:
        hot = a in reach
        ax.annotate("", xy=pos[b], xytext=pos[a], zorder=1,
                    arrowprops={"arrowstyle": "-|>", "color": "#c0392b" if hot else "#d5dae0", "lw": 1.3 if hot else 0.9,
                                    "shrinkA": 11, "shrinkB": 11, "connectionstyle": "arc3,rad=0.06", "alpha": 0.9 if hot else 0.8})
    for n in g.nodes:
        x, y = pos[n]
        silent = n not in v.component_dtcs
        ax.scatter([x], [y], s=190, color=color[g.nodes[n]["system"]], zorder=3, marker="D" if silent else "o",
                   edgecolor="#c0392b" if n == root else "white", linewidth=2.6 if n == root else 1.2)
        ax.text(x, y + 0.46, n.replace("_", " "), ha="center", va="bottom", fontsize=7.8, zorder=4,
                bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none", "alpha": 0.85})
    handles = [plt.Line2D([], [], marker="o", ls="", color=color[s], markersize=8, label=s) for s in systems]
    handles += [plt.Line2D([], [], marker="D", ls="", color=MUTED, markersize=7, label="silent: raises no code"),
                plt.Line2D([], [], marker="o", ls="", color="white", markeredgecolor="#c0392b",
                           markeredgewidth=2.2, markersize=9, label=f"injected fault: {root.replace('_', ' ')}"),
                plt.Line2D([], [], color="#c0392b", lw=1.5, label="paths the fault can follow")]
    ax.legend(handles=handles, loc="upper center", ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0.5, -0.01))
    ax.set_title(f"{name.title()}: how a {root.replace('_', ' ')} fault can spread through the vehicle",
                 loc="left", fontsize=13, fontweight="bold")
    ax.margins(0.05)
    ax.axis("off")
    fig.savefig(OUT / "fault_graph.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def results_chart():
    data = json.loads((ROOT / "results" / "latest.json").read_text())["per_vehicle"]
    names = list(data)
    def pct(k, n_key="n"):
        return [100 * data[v][k] / data[v][n_key] for v in names]
    series = [("Earliest-code rule", pct("base"), "#dfe3e8"),
              ("Set-cover rule", pct("cover"), "#a9b2bd"),
              ("FaultTrace top-1", pct("top1"), "#2f6fdb"),
              ("FaultTrace top-3", pct("top3"), "#12408f")]
    silent = [("Earliest-code rule", pct("silent_base", "silent_n"), "#dfe3e8"),
              ("Set-cover rule", pct("silent_cover", "silent_n"), "#a9b2bd"),
              ("FaultTrace", pct("silent_top1", "silent_n"), "#2f6fdb")]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.5, 1]})
    for ax, groups, title in ((axes[0], series, "All incidents: is the true root cause named?"),
                              (axes[1], silent, "Silent root causes only")):
        w = 0.8 / len(groups)
        for i, (label, vals, col) in enumerate(groups):
            xs = [j + (i - (len(groups) - 1) / 2) * w for j in range(len(names))]
            bars = ax.bar(xs, vals, w * 0.92, label=label, color=col)
            for b, val in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, val + 1.2, f"{val:.0f}", ha="center", fontsize=8, color=INK)
        ax.set_xticks(range(len(names)), names)
        ax.set_ylim(0, 108)
        ax.set_yticks(range(0, 101, 25), [f"{t}%" for t in range(0, 101, 25)])
        ax.grid(axis="y", color=GRID)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(length=0, colors=MUTED)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
        ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=2 if len(groups) == 3 else len(groups))
    fig.suptitle("Diagnosis accuracy on synthetic incidents", x=0.01, ha="left", fontsize=14, fontweight="bold")
    fig.text(0.01, -0.02, "Synthetic data only: incidents come from the same kind of model the diagnoser uses.",
             fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "results.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def verdicts_chart():
    """How far can each verdict be trusted? Share of incidents and accuracy per verdict."""
    ag = json.loads((ROOT / "results" / "latest.json").read_text())["agent"]
    tot = {k: sum(v[k] for v in ag.values()) for k in next(iter(ag.values()))}
    names = ["verified", "ambiguous", "unverified"]
    colors = {"verified": "#2a9d8f", "ambiguous": "#e0a31f", "unverified": "#c0392b"}
    share = [100 * tot[k] / tot["n"] for k in names]
    acc = [100 * tot[f"{k}_correct"] / tot[k] for k in names]
    group = 100 * tot["ambiguous_in_group"] / tot["ambiguous"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, vals, title in ((axes[0], share, "Share of incidents"), (axes[1], acc, "Root cause correct")):
        bars = ax.bar(names, vals, color=[colors[n] for n in names], width=0.55)
        for b, val in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, val + 2, f"{val:.0f}%", ha="center", fontsize=10, color=INK)
        ax.set_ylim(0, 108)
        ax.set_yticks(range(0, 101, 25), [f"{t}%" for t in range(0, 101, 25)])
        ax.grid(axis="y", color=GRID)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(length=0, colors=MUTED)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    fig.suptitle("What a verdict is worth", x=0.01, ha="left", fontsize=14, fontweight="bold")
    fig.text(0.01, -0.03, f"When the verdict is ambiguous, the true cause is the leader or a named rival {group:.0f}% of the time. "
             "Synthetic single-fault incidents, full workflow.", fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "verdicts.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def workflow():
    steps = [("Triage", "keep the main burst,\ndrop isolated and\nunknown codes"),
             ("Investigator", "rank every component\nby likelihood of the\nobserved code set"),
             ("Verifier", "re-simulate the\ncandidate, compare\nwith observed codes"),
             ("Reporter", "verdict, probability,\nevidence, alternatives")]
    fig, ax = plt.subplots(figsize=(12, 2.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(-0.3, 2.6)
    ax.axis("off")
    for i, (title, body) in enumerate(steps):
        x = 0.2 + i * 3.0
        ax.add_patch(FancyBboxPatch((x, 0.5), 2.4, 1.7, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc="#eef3fc" if i != 2 else "#e3edfb", ec="#2f6fdb", lw=1.4))
        ax.text(x + 1.2, 1.9, title, ha="center", va="center", fontsize=11.5, fontweight="bold", color="#12408f")
        ax.text(x + 1.2, 1.2, body, ha="center", va="center", fontsize=8.6, color=INK, linespacing=1.4)
        if i < 3:
            ax.annotate("", xy=(x + 3.0, 1.35), xytext=(x + 2.4, 1.35),
                        arrowprops={"arrowstyle": "-|>", "color": "#12408f", "lw": 1.6})
    ax.annotate("", xy=(6.7, 0.48), xytext=(8.3, 0.48), arrowprops={"arrowstyle": "-|>", "color": "#c0392b", "lw": 1.3,
                "connectionstyle": "arc3,rad=-0.5"})
    ax.text(7.5, -0.12, "rejected: try the next candidate (max 3)", ha="center", fontsize=8.2, color="#c0392b")
    fig.savefig(OUT / "workflow.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fault_graph()
    results_chart()
    verdicts_chart()
    workflow()
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
