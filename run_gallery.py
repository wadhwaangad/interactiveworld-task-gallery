#!/usr/bin/env python3
"""Validate every gallery task on the GPU machine and collect videos for the site.

    source ~/interactiveworld-assets/env.sh
    python3 run_gallery.py --iw ~/InteractiveWorld --gpu 0                 # all tasks, all layers
    python3 run_gallery.py --only WATCH-28008-ES FIND-14015-MOVED          # a few tasks
    python3 run_gallery.py --layers check verbal                           # skip story videos

Three layers per task, each resumable (a finished layer is skipped unless --force):

  check   simulator.sh run: the oracle actions after --prepare-task (WATCH: the full reference
          program, since --prepare-task cannot run continuous-watch tasks). Pass = score.success.
  story   simulator.sh run without preparation: the whole opening, then the oracle actions,
          rendered as site/results/<ID>/story.mp4. The video for the site.
  verbal  run_taskpack.sh --assistant oracle-verbal: scripted oracle advice and scripted Human
          through the real interaction runtime. Pass = native_taskpack_outcome.strict_success.
          No API key is used; the runner records no video in this mode.

Writes site/results/<ID>/{check,story,verbal}.json, logs, story.mp4 and site/results.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYERS = ("check", "story", "verbal")
WINDOWS = os.name == "nt"
# UTF-8 stdio: on Windows the runner's logs contain characters cp1252 cannot encode (e.g. a star),
# which crashes run_taskpack after the episode and loses results.jsonl.
ENV = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


def load_env_file(path):
    """Read env.ps1 ($env:X = 'v') or env.sh (export X=v) written by prepare_assets."""
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"""\s*(?:\$env:|export\s+)(\w+)\s*=\s*['"]?(.*?)['"]?\s*$""", line)
        if m:
            ENV.setdefault(m.group(1), m.group(2))


def launcher(iw, name):
    """Linux: the release's .sh wrappers. Windows: the .py entry point under the Isaac Python."""
    if not WINDOWS:
        return [str(iw / f"launch/{name}.sh")]
    py = ENV.get("ISAAC_PYTHON")
    if not py:
        sys.exit("ISAAC_PYTHON is not set: pass --env C:\\iw\\assets\\env.ps1")
    if name == "simulator":
        # the public CLI rejects @place_spot and instance (0) in --action; see faithful_simulator.py
        return [py, str(HERE / "faithful_simulator.py"), "--iw", str(iw)]
    return [py, str(iw / f"launch/{name}.py")]


# Release limitation found by running WATCH-28008: under --assistant oracle-verbal, run_taskpack.py
# always uses the scripted Human (_human_policy: "auto" -> "scripted"; no CLI flag changes it), and
# episode_loop._scripted_interaction_human_command only acts after the Assistant speaks. A WATCH
# Human must perform the opening unprompted, so the person never moves, the watched mistake never
# happens, and the episode times out with eval_valid=false.
WATCH_VERBAL = ("not supported in this release: oracle-verbal always scripts the Human, and the scripted "
                "Human only acts after the Assistant speaks, so it never performs a WATCH opening "
                "(the person stands still and the episode times out, eval_valid=false)")


def log_error(log):
    """Last simulator error line in a log, so a crash says why instead of just 'see log'."""
    try:
        lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    hits = [l.strip() for l in lines if "Error:" in l and "Warning" not in l]
    return hits[-1][:400] if hits else None


def failed_steps(steps):
    """'action -- REASON: detail' for each step whose primitives did not all succeed."""
    out = []
    for st in steps:
        bad = [o for o in (st.get("result") or {}).get("outcomes") or [] if not o.get("ok", True)]
        if bad:
            out.append(f"{st['action']} -- {bad[0].get('reason')}: {bad[0].get('detail') or ''}".rstrip(": "))
    return out


def replay_ok(score, failed, prepared):
    """score.success, except for an unprepared replay (WATCH) whose goals are all baseline-excluded.

    Unprepared, the scorer takes the initial world as the baseline, so a restore-the-state goal
    (WATCH-81020: the sink is off again) already holds there, is excluded, and leaves the score
    unscoreable even though the run ends in the goal state. Then require every goal to hold, the
    prohibitions to be clear and no step to have failed.
    """
    if score.get("success"):
        return True
    goals = (score.get("details") or {}).get("goals") or []
    return bool(not prepared and not score.get("scoreable") and goals and not failed
                and score.get("prohibitions_ok") and all(g.get("ok") for g in goals))


def sim_run(iw, task, out_json, log, *, prepare, actions, gpu, fpa, video=None, fps=8.0, seed=0):
    cmd = launcher(iw, "simulator") + ["run", "--taskpack", str(HERE / "taskpacks" / task["file"]),
           "--taskpack-sha256", task["sha256"], "--gpu", str(gpu), "--frames-per-action", str(fpa), "--seed", str(seed)]
    cmd += ["--prepare-task"] if prepare else ["--no-prepare-task"]
    if video:
        cmd += ["--video", str(video), "--video-fps", str(fps)]
    else:
        cmd += ["--no-render"]
    for a in actions:
        cmd += ["--action", a]
    with open(out_json, "w") as out, open(log, "w") as err:
        rc = subprocess.call(cmd, stdout=out, stderr=err, cwd=iw, env=dict(ENV, INTERACTIVEWORLD_OUTPUT_DIR=str(Path(out_json).parent / "work")))
    try:
        data = json.loads(Path(out_json).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"ok": False, "rc": rc, "seed": seed, "error": log_error(log) or "no JSON on stdout; see log"}
    steps = data.get("steps") or []
    failed = failed_steps(steps)
    score = data.get("score") or {}
    return {"ok": replay_ok(score, failed, prepare), "rc": rc, "score": score, "failed_actions": failed,
            "steps_run": len(steps), "steps_planned": len(actions), "seed": seed}


def verbal_run(iw, task, out_dir, log, *, gpu):
    cmd = launcher(iw, "run_taskpack") + ["--taskpack", str(HERE / "taskpacks" / task["file"]),
           "--taskpack-sha256", task["sha256"], "--assistant", "oracle-verbal",
           "--active-gpu", str(gpu), "--output-dir", str(out_dir)]
    with open(log, "w") as err:
        rc = subprocess.call(cmd, stdout=err, stderr=subprocess.STDOUT, cwd=iw, env=ENV)
    rows = []
    results = Path(out_dir) / "results.jsonl"
    if results.exists():
        rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {"ok": False, "rc": rc, "error": log_error(log) or "no results.jsonl; see log"}
    rec = rows[-1]
    native = rec.get("native_taskpack_outcome") or {}
    counters = rec.get("counters") or {}
    return {"ok": bool(native.get("strict_success")), "rc": rc, "native": native,
            "human_policy_status": counters.get("human_policy_status") or rec.get("human_policy_status"),
            "validity": {k: v for k, v in rec.items() if "valid" in k.lower() and not isinstance(v, (dict, list))},
            "transcript": rec.get("transcript") or []}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iw", type=Path, default=Path(r"C:\iw\InteractiveWorld") if WINDOWS else HERE.parent / "InteractiveWorld")
    ap.add_argument("--env", type=Path, default=Path(r"C:\iw\assets\env.ps1") if WINDOWS else None,
                    help="env file written by prepare_assets (env.ps1 or env.sh)")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--layers", nargs="*", default=list(LAYERS), choices=LAYERS)
    ap.add_argument("--frames-per-action", type=int, default=12, help="story video smoothness")
    ap.add_argument("--video-fps", type=float, default=8.0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--seed", type=int, default=0, help="simulator seed for the check and story layers")
    args = ap.parse_args()
    iw = args.iw.expanduser().resolve()
    if args.env and Path(args.env).exists():
        load_env_file(args.env)
    tasks = json.loads((HERE / "site/catalog.json").read_text(encoding="utf-8"))["tasks"]
    if args.only:
        tasks = [t for t in tasks if t["task_id"] in args.only]
    root = HERE / "site/results"
    for n, t in enumerate(tasks, 1):
        d = root / t["task_id"]
        d.mkdir(parents=True, exist_ok=True)
        for layer in args.layers:
            out = d / f"{layer}.json"
            if out.exists() and not args.force:
                continue
            print(f"[{n}/{len(tasks)}] {t['task_id']:26} {layer} ...", end="", flush=True)
            t0 = time.time()
            if layer == "check":
                res = sim_run(iw, t, d / "check.sim.json", d / "check.log", prepare=t["replay"]["prepare_task"],
                              actions=t["replay"]["actions"], gpu=args.gpu, fpa=4, seed=args.seed)
            elif layer == "story":
                res = sim_run(iw, t, d / "story.sim.json", d / "story.log", prepare=False,
                              actions=t["replay"]["story_actions"], gpu=args.gpu, fpa=args.frames_per_action,
                              video=d / "story.mp4", fps=args.video_fps, seed=args.seed)
                res["video"] = "story.mp4" if (d / "story.mp4").exists() else None
            elif t.get("family") == "WATCH" or t.get("category") == "Prevention":
                res = {"ok": None, "unsupported": WATCH_VERBAL}  # see WATCH_VERBAL; nothing to run
            else:
                res = verbal_run(iw, t, d / "verbal", d / "verbal.log", gpu=args.gpu)
            res["seconds"] = round(time.time() - t0, 1)
            out.write_text(json.dumps(res, indent=1, default=str))
            print(f" {'n/a' if res['ok'] is None else 'PASS' if res['ok'] else 'FAIL'} ({res['seconds']}s)")
    summary = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        summary[d.name] = {layer: json.loads((d / f"{layer}.json").read_text())
                           for layer in LAYERS if (d / f"{layer}.json").exists()}
    blob = {"generated": time.strftime("%Y-%m-%d %H:%M"), "results": summary}
    (HERE / "site/results.json").write_text(json.dumps(blob, indent=1, default=str))
    (HERE / "site/results.js").write_text("window.GALLERY_RESULTS = " + json.dumps(blob, default=str) + ";\n")
    bad = [k for k, v in summary.items() if any(r.get("ok") is False for r in v.values())]
    print(f"\n{len(summary)} tasks with results; failing: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
