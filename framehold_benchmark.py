"""Read-only analysis of a PresentMon CSV exported for Fortnite."""

from __future__ import annotations

import csv
import math
import os
from statistics import mean, median


def _percentile(sorted_values: list[float], portion: float) -> float:
    position = (len(sorted_values) - 1) * portion
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def analyze_csv(path: str) -> dict:
    if not os.path.isfile(path) or os.path.getsize(path) > 100_000_000:
        raise ValueError("csv file is missing or exceeds 100 mb")
    present = []
    cpu = []
    gpu = []
    latency = []
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "MsBetweenPresents" not in reader.fieldnames:
            raise ValueError("csv needs the presentmon msbetweenpresents column")
        for row in reader:
            if "Application" in row and str(row["Application"]).lower() not in ("fortniteclient-win64-shipping.exe", "fortniteclient-win64-shipping"):
                continue
            try:
                value = float(row["MsBetweenPresents"])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value) or not 0.1 <= value <= 1000:
                continue
            present.append(value)
            for name, target in (("MsCPUBusy", cpu), ("MsGPUBusy", gpu), ("MsPCLatency", latency)):
                try:
                    measurement = float(row.get(name, ""))
                    if math.isfinite(measurement) and measurement >= 0:
                        target.append(measurement)
                except (TypeError, ValueError):
                    pass
            if len(present) > 2_000_000:
                raise ValueError("csv contains too many frame rows")
    if len(present) < 100:
        raise ValueError("need at least 100 valid fortnite frames")
    ordered = sorted(present)
    return {
        "frames": len(present),
        "average_fps": 1000 * len(present) / sum(present),
        "median_ms": median(present),
        "p95_ms": _percentile(ordered, 0.95),
        "p99_ms": _percentile(ordered, 0.99),
        "cpu_busy_ms": mean(cpu) if cpu else None,
        "gpu_busy_ms": mean(gpu) if gpu else None,
        "pc_latency_ms": median(latency) if latency else None,
    }
