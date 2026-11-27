"""The recommendations in short: for one file (a verdict and its few most useful actions, in order) and
across many (how many are ready to use, the changes that come up most, and the files that need the most
attention). Built from what the check already found, so it never says anything the detail doesn't."""

from __future__ import annotations

from collections import Counter

# Findings that are information, not problems (the same rule as the app's "What's holding it back")
INFO_STARTS = ("No problems", "Focus:", "Focus mode", "The sharpest detail")
INFO_HAS = ("fps: smooth motion", "holds up well")


def problems(findings: list[str]) -> list[str]:
    return [f for f in findings if not f.startswith(INFO_STARTS) and not any(x in f for x in INFO_HAS)]


def verdict(n_problems: int, n_fixes: int, n_settings: int) -> tuple[str, str]:
    """(level, words): "good", "fix" or "attention"."""
    if not n_problems and not n_fixes:
        return "good", "Ready to use as it is"
    if n_problems <= 1 and n_settings <= 1:
        return "fix", "Good, with a quick fix" if n_fixes else "Good, one thing to watch"
    return "attention", "Needs attention: a fix helps now, and a few changes next time"


def for_file(findings: list[str], fixes_on: list[dict], settings: list, habits: list[str], most: int = 5) -> dict:
    """The verdict and up to `most` actions: fixes for this file first, then settings for next time, then a habit."""
    probs = problems(findings)
    level, words = verdict(len(probs), len(fixes_on), len(settings))
    items = [{"when": "now", "title": f"Fix this file: {f['label']}", "why": f.get("why", "")} for f in fixes_on]
    items += [{"when": "next", "title": f"Next time: {s[0]} → {s[1]}", "why": s[2]} for s in settings]
    if habits:
        items.append({"when": "habit", "title": habits[0], "why": ""})
    return {"level": level, "verdict": words, "problems": len(probs), "items": items[:most],
            "more": max(0, len(items) - most)}


def across(files: list[dict]) -> dict:
    """files: {"name", "kind", "findings", "fixes_on", "settings", "habits"} for each checked file."""
    n = len(files)
    per = [(f, for_file(f["findings"], f["fixes_on"], f["settings"], f["habits"])) for f in files]
    good = [f["name"] for f, r in per if r["level"] == "good"]
    fix = [f["name"] for f, r in per if r["level"] == "fix"]
    attention = [f["name"] for f, r in per if r["level"] == "attention"]
    # the setting changes that come up most (each setting once per file; its most common advice)
    by_setting: dict[str, list] = {}
    for f in files:
        for s in {s[0]: s for s in f["settings"]}.values():
            by_setting.setdefault(s[0], []).append((f["name"], s[1], s[2]))
    changes = []
    for name, rows in by_setting.items():
        advice = Counter(r[1] for r in rows).most_common()
        changes.append({"setting": name, "change": advice[0][0] if len(advice) == 1 else f"{advice[0][0]} (varies: see each file)",
                        "why": rows[0][2], "files": [r[0] for r in rows], "count": len(rows)})
    changes.sort(key=lambda c: (-c["count"], c["setting"]))
    fixes = Counter(x["label"] for f in files for x in f["fixes_on"])
    habits = Counter(h for f in files for h in f["habits"][:2])
    worst = sorted(((len(problems(f["findings"])), f["name"]) for f in files if problems(f["findings"])), reverse=True)[:3]
    if not n:
        headline = "Nothing checked yet."
    else:
        parts = [f"{len(good)} of {n} ready to use as they are"]
        if fix:
            parts.append(f"{len(fix)} good with a quick fix")
        if attention:
            parts.append(f"{len(attention)} need attention")
        headline = ", ".join(parts) + "."
        if changes:
            c = changes[0]
            headline += f" Most useful change next time: {c['setting'].lower()} ({c['count']} of {n})."
    return {"count": n, "headline": headline, "good": good, "fix": fix, "attention": attention,
            "changes": changes[:6], "fixes": [{"label": k, "count": v} for k, v in fixes.most_common(5)],
            "habits": [{"text": k, "count": v} for k, v in habits.most_common(3)],
            "worst": [{"name": nm, "problems": p} for p, nm in worst]}
