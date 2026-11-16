"""Fix WATCH results written by an older run_gallery.py: oracle-verbal -> n/a (WATCH_VERBAL), and
re-judge unprepared oracle replays with replay_ok (baseline-excluded restore goals)."""
import json
from pathlib import Path
from run_gallery import WATCH_VERBAL, replay_ok

HERE = Path(__file__).resolve().parent
cat = {t["task_id"]: t for t in json.loads((HERE / "site/catalog.json").read_text(encoding="utf-8"))["tasks"]}
for d in sorted((HERE / "site/results").iterdir()):
    if cat.get(d.name, {}).get("family") != "WATCH":
        continue
    c = d / "check.json"
    if c.exists():
        j = json.loads(c.read_text())
        if "score" in j and not j["ok"] and replay_ok(j["score"], j.get("failed_actions") or [], False):
            j["ok"] = True
            j["note"] = "unprepared replay: every goal holds but is baseline-excluded; passed by replay_ok"
            c.write_text(json.dumps(j, indent=1))
            print(d.name, "check -> pass (baseline-excluded goals all hold)")
    f = d / "verbal.json"
    if not f.exists():
        continue
    j = json.loads(f.read_text())
    if j.get("ok") is None:
        continue
    rows = d / "verbal" / "results.jsonl"
    pm = {}
    if rows.exists():
        lines = [l for l in rows.read_text(encoding="utf-8").splitlines() if l.strip()]
        pm = json.loads(lines[-1]).get("process_metrics", {}) if lines else {}
    note = f"ran once to confirm: {pm.get('watch_opening_index')}/{pm.get('watch_opening_total')} opening actions executed"
    f.write_text(json.dumps({"ok": None, "unsupported": WATCH_VERBAL, "seconds": j.get("seconds"),
                             "observed": {"ok": j["ok"], "native": j.get("native"), "validity": j.get("validity"),
                                          "note": note}}, indent=1))
    print(d.name, "->", note)
