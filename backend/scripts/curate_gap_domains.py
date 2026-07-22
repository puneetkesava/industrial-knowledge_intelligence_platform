#!/usr/bin/env python3
"""Curate a proportional per-domain subset into Industrial_Dataset_Demo (additive).

Skips files already present in the demo folder (same relative path).
Reports shortfalls when a domain cannot hit its target.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

DEFAULT_SOURCE = Path(r"D:/Industrial_Dataset")
DEFAULT_DEST = Path(r"D:/Industrial_Dataset_Demo")

# Prefer text-rich categories; drawings last so proportional fill still includes some.
CATEGORY_ORDER = [
    "manual",
    "test_report",
    "maintenance",
    "sop",
    "safety",
    "sensor",
    "regulation",
    "work_order",
    "datasheet",
    "asset_register",
    "certificate",
    "drawing",
]


def _l2_category(rel_parts: list[str]) -> str:
    if len(rel_parts) < 2:
        return "uncategorized"
    raw = rel_parts[1].lower().replace("-", "_").replace(" ", "_")
    # strip leading "01_" style prefixes
    if "_" in raw and raw.split("_", 1)[0].isdigit():
        raw = raw.split("_", 1)[1]
    aliases = {
        "drawings": "drawing",
        "drawing": "drawing",
        "instructions_and_manuals": "manual",
        "instruction_manuals": "manual",
        "manuals": "manual",
        "manual": "manual",
        "maintenance": "maintenance",
        "regulations": "regulation",
        "regulation": "regulation",
        "safety": "safety",
        "sensors": "sensor",
        "sensor": "sensor",
        "sop_s": "sop",
        "sops": "sop",
        "sop": "sop",
        "spare_parts_or_product_descriptions": "datasheet",
        "product_descriptions_and_spare_parts": "datasheet",
        "product_descriptions": "datasheet",
        "spare_parts": "datasheet",
        "work_orders": "work_order",
        "work_order": "work_order",
        "asset_register": "asset_register",
        "certificates": "certificate",
        "certification": "certificate",
        "incident_or_inspection": "test_report",
        "inspection_or_incident": "test_report",
        "inspection": "test_report",
    }
    return aliases.get(raw, "uncategorized")


def _existing_demo_rels(dest: Path) -> set[str]:
    if not dest.exists():
        return set()
    out: set[str] = set()
    for p in dest.rglob("*"):
        if p.is_file():
            out.add(p.relative_to(dest).as_posix())
    return out


def _list_domain_files(source: Path, domain: str) -> dict[str, list[Path]]:
    root = source / domain
    by_cat: dict[str, list[Path]] = defaultdict(list)
    if not root.is_dir():
        return by_cat
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.suffix.lower() in {".tmp", ".ds_store"}:
            continue
        rel = p.relative_to(source)
        cat = _l2_category(list(rel.parts))
        by_cat[cat].append(p)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x.as_posix().lower())
    return by_cat


def _proportional_sample(
    by_cat: dict[str, list[Path]],
    need: int,
    already: set[str],
    source: Path,
    rng: random.Random,
) -> list[Path]:
    """Sample up to `need` files, spread across categories, skipping already-copied rels."""
    available: dict[str, list[Path]] = {}
    for cat, files in by_cat.items():
        kept = []
        for f in files:
            rel = f.relative_to(source).as_posix()
            if rel not in already:
                kept.append(f)
        if kept:
            available[cat] = kept

    total_avail = sum(len(v) for v in available.values())
    if total_avail == 0 or need <= 0:
        return []

    need = min(need, total_avail)
    cats = sorted(available.keys(), key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c))

    # Initial proportional quotas (at least 1 when category has files and need is large enough)
    quotas: dict[str, int] = {}
    remaining = need
    for i, cat in enumerate(cats):
        share = max(1, round(need * len(available[cat]) / total_avail)) if need >= len(cats) else 0
        quotas[cat] = min(share, len(available[cat]))
        remaining -= quotas[cat]

    # Fix rounding drift
    while remaining > 0:
        progressed = False
        for cat in cats:
            if remaining <= 0:
                break
            if quotas[cat] < len(available[cat]):
                quotas[cat] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    while remaining < 0:
        for cat in reversed(cats):
            if remaining >= 0:
                break
            if quotas[cat] > 0:
                quotas[cat] -= 1
                remaining += 1

    chosen: list[Path] = []
    for cat in cats:
        pool = available[cat][:]
        rng.shuffle(pool)
        chosen.extend(pool[: quotas[cat]])

    # Top up if still short
    if len(chosen) < need:
        chosen_set = {p.relative_to(source).as_posix() for p in chosen}
        leftovers: list[Path] = []
        for cat in cats:
            for f in available[cat]:
                rel = f.relative_to(source).as_posix()
                if rel not in chosen_set:
                    leftovers.append(f)
        rng.shuffle(leftovers)
        chosen.extend(leftovers[: need - len(chosen)])

    return chosen[:need]


def curate(
    source: Path,
    dest: Path,
    domains: dict[str, int],
    seed: int = 42,
) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    already = _existing_demo_rels(dest)
    rng = random.Random(seed)
    report: dict = {"copied": {}, "shortfall": {}, "skipped_existing": {}, "by_category": {}}

    for domain, target in domains.items():
        by_cat = _list_domain_files(source, domain)
        # How many already in demo for this domain?
        existing_domain = {r for r in already if r.split("/", 1)[0] == domain}
        need = max(0, target - len(existing_domain))
        selected = _proportional_sample(by_cat, need, already, source, rng)

        copied = 0
        cat_counts: dict[str, int] = defaultdict(int)
        for src in selected:
            rel = src.relative_to(source)
            dst = dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                continue
            shutil.copy2(src, dst)
            already.add(rel.as_posix())
            copied += 1
            cat_counts[_l2_category(list(rel.parts))] += 1

        final_count = len({r for r in already if r.split("/", 1)[0] == domain})
        report["copied"][domain] = copied
        report["skipped_existing"][domain] = len(existing_domain)
        report["by_category"][domain] = dict(cat_counts)
        if final_count < target:
            report["shortfall"][domain] = {
                "target": target,
                "have": final_count,
                "missing": target - final_count,
                "source_available": sum(len(v) for v in by_cat.values()),
            }
        else:
            report["shortfall"][domain] = None

    report["dest_total_files"] = len(already)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate gap domains into demo corpus")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--targets",
        type=str,
        default="",
        help='JSON object e.g. {"Pumps":40,"Turbines":40}',
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.targets:
        domains = {k: int(v) for k, v in json.loads(args.targets).items()}
    else:
        domains = {
            "Pumps": 40,
            "Turbines": 40,
            "Compressors": 40,
            "Chemical_Plants": 15,
            "Valves": 40,  # absolute demo total target
            "Oil_Refineries": 15,
            "Broilers": 40,  # dataset folder name for Boilers
        }

    report = curate(args.source, args.dest, domains, seed=args.seed)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
