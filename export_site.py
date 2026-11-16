#!/usr/bin/env python3
"""Build docs/, the public GitHub Pages copy of the site.

    python export_site.py

Copies the page, catalog, results, story videos and the TaskPacks. Leaves out the simulator logs,
the raw *.sim.json dumps and the oracle-verbal work folders: they are large and carry local paths.
In the results it keeps:
  * local paths, rewritten relative to the gallery folder (or ~);
  * a layer that failed only because it ran against an older build of its TaskPack (SHA256
    mismatch), dropped, since that result no longer describes the published pack;
  * a "see log" error, replaced by the last error line of that log.
"""
import json
import re
import shutil
from pathlib import Path

import run_gallery as rg

HERE = Path(__file__).resolve().parent
SITE, DOCS = HERE / "site", HERE / "docs"
LOCAL = [(str(HERE), "."), (str(HERE).replace("\\", "/"), ".")]
HOME = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\"' ]+", re.I)


def scrub(x):
    if isinstance(x, str):
        for a, b in LOCAL:
            x = x.replace(a, b)
        return HOME.sub("~", x)
    if isinstance(x, list):
        return [scrub(v) for v in x]
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items()}
    return x


def layer(d, name):
    f = d / f"{name}.json"
    if not f.exists():
        return None
    r = json.loads(f.read_text(encoding="utf-8"))
    err = r.get("error") or ""
    if "SHA256 mismatch" in err:
        return None
    if "see log" in err:
        r["error"] = rg.log_error(d / f"{name}.log") or err.replace("; see log", "")
    return r


def main():
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir()
    for f in ("index.html", "catalog.js", "catalog.json", "preflight_guide.json", "preflight_process.json"):
        if (SITE / f).exists():
            shutil.copy2(SITE / f, DOCS / f)
    results = {}
    in_gallery = {t["task_id"] for t in json.loads((SITE / "catalog.json").read_text(encoding="utf-8"))["tasks"]}
    for d in sorted(p for p in (SITE / "results").iterdir() if p.is_dir() and p.name in in_gallery):
        rec = {k: v for k in rg.LAYERS if (v := layer(d, k)) is not None}
        if (d / "story.mp4").exists():
            (DOCS / "results" / d.name).mkdir(parents=True)
            shutil.copy2(d / "story.mp4", DOCS / "results" / d.name / "story.mp4")
        elif "story" in rec:
            rec["story"]["video"] = None
        results[d.name] = scrub(rec)
    stamp = json.loads((SITE / "results.json").read_text(encoding="utf-8"))["generated"]
    blob = {"generated": stamp, "results": results}
    (DOCS / "results.json").write_text(json.dumps(blob, indent=1), encoding="utf-8")
    (DOCS / "results.js").write_text("window.GALLERY_RESULTS = " + json.dumps(blob) + ";\n", encoding="utf-8")
    shutil.copytree(HERE / "taskpacks", DOCS / "taskpacks")  # byte-for-byte: the pinned hashes need LF
    (DOCS / ".nojekyll").write_text("")
    leaks = [p for p in DOCS.rglob("*") if p.is_file() and p.suffix in {".js", ".json", ".html"}
             and HOME.search(p.read_text(encoding="utf-8", errors="replace"))]
    size = sum(p.stat().st_size for p in DOCS.rglob("*") if p.is_file()) / 2**20
    print(f"docs/: {len(results)} tasks, {sum(1 for _ in DOCS.rglob('*.mp4'))} videos, {size:.1f} MB; "
          f"local paths left in: {[str(p.relative_to(DOCS)) for p in leaks] or 'none'}")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
