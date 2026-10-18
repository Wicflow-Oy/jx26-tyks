"""Warm the caches before serving (CONTRACTS.md section 7) and print timings:

    python -m aei.precompute [--weeks all|demo] [--narration]

- signals per week, written by `brief.precompute` to config.CACHE_DIR/signals;
- the replay slider's tick marks (P1 and signal counts per week) in config.CACHE_DIR/replay_weeks.json;
- the demo-Monday briefs, built once each as a check and a timing;
- with --narration and ANTHROPIC_API_KEY set: model narration for every demo-Monday item, recorded for replay, so the
  public demo shows it with no key. Each call counts toward the daily spend cap.
"""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import pandas as pd

from . import brief, data, narrator
from . import config as C


def _day(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def replay_range() -> list[str]:
    """Every as-of Sunday the replay slider offers, oldest first."""
    return [_day(d) for d in pd.date_range(data.week_end(C.REPLAY_FIRST_WEEK), C.DATA_END, freq="7D")]


def _ticks_file() -> Path:
    return Path(C.CACHE_DIR) / "replay_weeks.json"


def read_ticks(ds) -> dict:
    """{as_of: {n_p1, n_signals}} for the precomputed weeks; empty when missing or written by other code."""
    try:
        saved = json.loads(_ticks_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved.get("weeks", {}) if saved.get("fingerprint") == brief.fingerprint(ds) else {}


def write_ticks(ds, rows: list[dict]) -> None:
    """Merge rows from `brief.precompute` into the tick file. Written to a temp file and renamed, because the API may
    read it while the background precompute runs."""
    weeks = read_ticks(ds) | {r["as_of"]: {"n_p1": r["n_p1"], "n_signals": r["n_signals"]} for r in rows}
    file = _ticks_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=file.parent, suffix=".tmp", delete=False) as fh:
        json.dump({"fingerprint": brief.fingerprint(ds), "weeks": weeks}, fh)
    os.replace(fh.name, file)


def replay_weeks(ds) -> list[dict]:
    """The slider's tick marks over the replay range. Counts are None for weeks not precomputed yet: computing all of
    them takes about a minute, which a request cannot wait for."""
    ticks = read_ticks(ds)
    return [
        {
            "as_of": a,
            "monday": _day(pd.Timestamp(a) + pd.Timedelta(days=1)),
            "n_p1": ticks.get(a, {}).get("n_p1"),
            "n_signals": ticks.get(a, {}).get("n_signals"),
        }
        for a in replay_range()
    ]


def warm_signals(ds, weeks="all") -> list[dict]:
    """Compute and cache the signals for `weeks` ("all", "demo" or a list of as-of dates) and record the tick marks."""
    rows = brief.precompute(ds, weeks)
    in_range = set(replay_range())
    write_ticks(ds, [r for r in rows if r["as_of"] in in_range])
    return rows


def demo_as_ofs() -> list[str]:
    return [_day(pd.Timestamp(m) - pd.Timedelta(days=1)) for m in C.DEMO_MONDAYS]


def record_narration(ds) -> tuple[int, int]:
    """Narrate every demo-Monday brief item for infection control, and each unusual pattern also for the ED heads-up.
    Returns (model narrations recorded or already cached, template fallbacks)."""
    recorder = narrator.CachedNarrator(narrator.AnthropicNarrator(), record=True)
    model, fallback = 0, 0
    for as_of in demo_as_ofs():
        for section in brief.build_brief(ds, as_of)["sections"]:
            audiences = ("infection_control", "ed") if section["key"] == "unusual_patterns" else ("infection_control",)
            for item in section["items"]:
                for audience in audiences:
                    if recorder.narrate(item["template_id"], item["slots"], audience=audience).fallback_reason:
                        fallback += 1
                    else:
                        model += 1
    return model, fallback


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m aei.precompute", description="Warm the caches before serving.")
    parser.add_argument(
        "--weeks",
        choices=("all", "demo"),
        default="all",
        help="all: the whole replay range (about a minute); demo: the demo Mondays and the weeks before",
    )
    parser.add_argument(
        "--narration",
        action="store_true",
        help="also record model narration for the demo weeks (needs ANTHROPIC_API_KEY)",
    )
    args = parser.parse_args(argv)
    start = time.perf_counter()
    ds = data.load()
    print(f"data loaded in {time.perf_counter() - start:.1f} s")

    t = time.perf_counter()
    rows = warm_signals(ds, args.weeks)
    slowest = max(rows, key=lambda r: r["seconds"])
    print(
        f"signals: {len(rows)} weeks in {time.perf_counter() - t:.1f} s "
        f"(slowest {slowest['as_of']}, {slowest['seconds']:.1f} s); tick marks in {_ticks_file()}"
    )

    for as_of in demo_as_ofs():
        t = time.perf_counter()
        counts = brief.build_brief(ds, as_of)["counts"]
        print(
            f"brief for Monday after {as_of}: {counts['P1']} P1, {counts['P2']} P2 in {time.perf_counter() - t:.2f} s"
        )

    if args.narration:
        if narrator.key_set():
            t = time.perf_counter()
            model, fallback = record_narration(ds)
            print(
                f"narration: {model} recorded or cached, {fallback} template fallbacks in {time.perf_counter() - t:.1f} s"
            )
        else:
            print("narration: skipped, ANTHROPIC_API_KEY is not set (the demo uses the templates)")
    print(f"done in {time.perf_counter() - start:.1f} s")


if __name__ == "__main__":
    main()
