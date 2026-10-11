"""Render the measured scaling comparison. Requires matplotlib, no server access."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import ScalarFormatter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--extend", type=Path, help="Replace matching cases with a later extended suite"
    )
    parser.add_argument(
        "--host-label", help="Hardware and OS caption; defaults to the recorded platform"
    )
    args = parser.parse_args()
    data = json.loads((args.folder / "results.json").read_text())
    if args.extend:
        extra = json.loads((args.extend / "results.json").read_text())
        for key in ("platform", "gpu", "steps", "warmup", "repeats", "seed", "dt_ms", "protocols"):
            if data[key] != extra[key]:
                parser.error(f"Cannot combine suites with different {key}")
        combined = {(c["activity"], c["neurons"], c["fanout"]): c for c in data["cases"]}
        combined.update({(c["activity"], c["neurons"], c["fanout"]): c for c in extra["cases"]})
        data["cases"] = list(combined.values())
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 11.5), layout="constrained")
    colors = {"cpu": "#14609c", data["gpu"]: "#ad480d"}
    gpu_name = "Metal/MPS" if data["gpu"] == "mps" else data["gpu"].upper()
    names = {"cpu": "CPU · NumPy", data["gpu"]: f"GPU · {gpu_name}"}
    for ax, activity, title in zip(
        axes,
        ["sparse", "active"],
        [
            "Редкая активность · около 0,33 Гц / нейрон",
            "Частая активность · около 31–33 Гц / нейрон",
        ],
    ):
        cases = [c for c in data["cases"] if c["activity"] == activity and c["fanout"] == 10]
        cases.sort(key=lambda c: c["neurons"])
        xs = [c["neurons"] for c in cases]
        for device in ["cpu", data["gpu"]]:
            summaries = [c["summary"][device] for c in cases]
            means = [s["mean_ms"] for s in summaries]
            ax.plot(
                xs,
                means,
                marker="o" if device == "cpu" else "s",
                color=colors[device],
                linewidth=2,
                label=names[device],
            )
            ax.fill_between(
                xs,
                [s["run_mean_min_ms"] for s in summaries],
                [s["run_mean_max_ms"] for s in summaries],
                color=colors[device],
                alpha=0.15,
            )
            for case, x, y in zip(cases, xs, means):
                if max(xs) > 20000 and x not in (100, 1000, 10000, 50000, max(xs)):
                    continue
                other = data["gpu"] if device == "cpu" else "cpu"
                offset = 10 if y >= case["summary"][other]["mean_ms"] else -16
                ax.annotate(
                    f"{y:.3f}",
                    (x, y),
                    xytext=(0, offset),
                    textcoords="offset points",
                    ha="center",
                    fontsize=9,
                    color=colors[device],
                )
        ax.set_xscale("log")
        ax.set_yscale("log")
        high = max(c["summary"][d]["run_mean_max_ms"] for c in cases for d in names)
        ax.set_ylim(0.007, max(3, high * 2))
        ax.set_ylabel("Среднее время такта, мс\nменьше — быстрее", fontsize=10)
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
        ax.set_yticks(
            [v for v in [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100] if v < max(3.01, high * 2)]
        )
        ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.grid(True, which="major", alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(loc="upper left", fontsize=10)
        ticks = (
            xs if max(xs) <= 20000 else [x for x in xs if x in (100, 1000, 10000, 100000, max(xs))]
        )
        ax.set_xticks(ticks, [f"{x:,}".replace(",", " ") for x in ticks])
        ax.set_xlabel("Нейронов · 10 исходящих связей на нейрон", fontsize=10)
    ax = axes[2]
    cases = [c for c in data["cases"] if c["activity"] == "active" and c["edges"] == 500000]
    cases.sort(key=lambda c: c["neurons"])
    xs = np.arange(len(cases))
    for device, offset in [("cpu", -0.18), (data["gpu"], 0.18)]:
        summaries = [c["summary"][device] for c in cases]
        means = np.array([s["mean_ms"] for s in summaries])
        errors = [
            means - [s["run_mean_min_ms"] for s in summaries],
            [s["run_mean_max_ms"] for s in summaries] - means,
        ]
        bars = ax.bar(
            xs + offset,
            means,
            width=0.34,
            color=colors[device],
            label=names[device],
            yerr=errors,
            capsize=4,
        )
        ax.bar_label(bars, fmt="%.3f", padding=9, fontsize=9)
    ax.set_xticks(xs, [f"{c['neurons']:,}".replace(",", " ") for c in cases])
    ax.set_ylim(0, max(c["summary"][d]["run_mean_max_ms"] for c in cases for d in names) * 1.3)
    ax.set_xlabel("Нейронов · 500 000 связей в каждой сети", fontsize=10)
    ax.set_ylabel("Среднее время такта, мс\nменьше — быстрее", fontsize=10)
    ax.set_title(
        "Активные сети · одинаковое число связей",
        loc="left",
        fontsize=12,
        fontweight="bold",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", fontsize=9, ncol=2)
    fig.suptitle("CPU и GPU: размер, активность и плотность сети", fontsize=17, fontweight="bold")
    fig.supxlabel(
        f"{args.host_label or data['platform']} · {data['repeats']} × {data['steps']:,} тактов "
        f"после прогрева ({data['warmup']})\n"
        "Полосы: диапазон средних прогонов. Верхние графики: логарифмические оси.\n"
        "GPU: завершение + передача входов и спайков. Без среды, телеметрии и отрисовки.\n"
        "Энергопотребление не измерялось.",
        fontsize=9,
    )
    output = args.extend or args.folder
    fig.savefig(output / "scaling.png", dpi=170)
    fig.savefig(output / "scaling.svg")
    plt.close(fig)


if __name__ == "__main__":
    main()
