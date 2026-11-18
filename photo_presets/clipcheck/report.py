"""Writes the results: a Word report (opens cleanly in Google Drive and
converts to a Google Doc) and a spreadsheet with one row per file."""

import csv
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt

from photo_presets.clipcheck import analyze

TABLE_STYLE = "Light Grid Accent 1"


def _table(doc, rows: list[list[str]], header: bool = True) -> None:
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = TABLE_STYLE
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(text)
            if header and r == 0:
                for run in cell.paragraphs[0].runs:
                    run.bold = True
    doc.add_paragraph()


def _bullets(doc, items: list[str], style: str = "List Bullet") -> None:
    for item in items:
        doc.add_paragraph(item, style=style)


def write_docx(results: list, path: Path, compare: bool = False, title: str = "Shot check",
               extras: dict | None = None) -> Path:
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_heading(title, 0)
    good = [r for r in results if isinstance(r, analyze.Result)]
    videos, photos = sum(r.kind == "video" for r in good), sum(r.kind == "photo" for r in good)
    doc.add_paragraph(f"{datetime.now():%B %-d, %Y} · {videos} video{'s' * (videos != 1)}, "
                      f"{photos} photo{'s' * (photos != 1)}").runs[0].italic = True
    doc.add_paragraph("Settings come from the camera's own data in each file; sharpness, grain, exposure and "
                      "panning are measured from the pixels. Sharpness and grain numbers compare best between "
                      "files from the same camera.")

    if compare:
        for kind in ("video", "photo"):
            group = [r for r in good if r.kind == kind]
            if len(group) >= 2:
                header, rows, notes = analyze.comparison(group)
                doc.add_heading(f"Side by side ({kind}s)", 1)
                for heading, pair in notes:
                    doc.add_heading(f"What's different: {heading}", 2)
                    _bullets(doc, pair or ["No notable differences in settings or measurements."])
                _table(doc, [header] + rows)

    for r in results:
        doc.add_heading(r.name, 1)
        if isinstance(r, analyze.Failed):
            doc.add_paragraph(f"Could not be analyzed: {r.error}")
            continue
        doc.add_paragraph(str(Path(r.path).parent)).runs[0].italic = True
        doc.add_heading("Summary", 2)
        _bullets(doc, r.advice.findings)
        more = (extras or {}).get(r.path, {})
        if more.get("moments"):
            doc.add_heading("When it happens", 2)
            _table(doc, [["Time", "What", "Detail"]] + [[m["clock"], m["label"], m["detail"]] for m in more["moments"]])
        if more.get("fixes"):
            doc.add_heading("Fixes for this file", 2)
            _table(doc, [["Fix", "Why", "What it can't do"]] + [[x["label"], x["why"], x["limit"]] for x in more["fixes"]])
        doc.add_heading("Settings", 2)
        _table(doc, [["Setting", "Value"]] + [list(row) for row in analyze.settings_rows(r)])
        doc.add_heading("Measurements", 2)
        _table(doc, [["Measurement", "Value"]] + [list(row) for row in analyze.measurement_rows(r)])
        if r.advice.settings:
            doc.add_heading("Setting recommendations", 2)
            _table(doc, [["Setting", "Recommendation", "Why"]] + [list(s) for s in r.advice.settings])
        if r.advice.habits:
            doc.add_heading("Shooting habits", 2)
            _bullets(doc, r.advice.habits, "List Number")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def write_csv(results: list, path: Path) -> Path:
    rows, columns = [], ["file", "folder", "kind", "error"]
    for r in results:
        row = {"file": r.name, "folder": str(Path(r.path).parent), "kind": r.kind,
               "error": getattr(r, "error", "") or ""}
        if isinstance(r, analyze.Result):
            for label, value in analyze.settings_rows(r) + analyze.measurement_rows(r):
                row[label] = value
            row["findings"] = " | ".join(r.advice.findings)
            row["recommendations"] = " | ".join(f"{s[0]}: {s[1]}" for s in r.advice.settings)
        for key in row:
            if key not in columns:
                columns.append(key)
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path
