"""Find a box layout the world builder can site for the PACK ports (needs the GPU; run alone).

    python -u pack_layout_probe.py [--task PACK-BEACH-HOLIDAY]

All six PACK ports put three packing_box bodies (same model cjhskr) in Rs_int living_room_0, and
the builder rejects every joint layout ("frozen container body ... cannot be sited"). The release
only ever uses one packing_box per task. Each variant here moves boxes to other rooms, writes a
scratch pack, and runs `simulator.py run --prepare-task` with no actions: building the world and
the opening is the whole test, so a failure costs ~80 s.
"""
import argparse
import copy
import hashlib
import json
import subprocess
import time
from pathlib import Path

import run_gallery as rg

HERE = Path(__file__).resolve().parent
VARIANTS = {
    "E1-spread": {"box_1": "living_room_0", "box_2": "bedroom_0", "box_3": "kitchen_0"},
    "E2-two-in-living": {"box_1": "living_room_0", "box_2": "living_room_0", "box_3": "bedroom_0"},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="PACK-BEACH-HOLIDAY")
    ap.add_argument("--iw", type=Path, default=Path(r"C:\iw\InteractiveWorld"))
    ap.add_argument("--env", type=Path, default=Path(r"C:\iw\assets\env.ps1"))
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    rg.load_env_file(args.env)
    base = json.loads((HERE / f"taskpacks/pack/{args.task}.taskpack.json").read_text(encoding="utf-8"))
    out = HERE / "probe"
    out.mkdir(exist_ok=True)
    report = {}
    for name, rooms in VARIANTS.items():
        if args.only and name not in args.only:
            continue
        p = copy.deepcopy(base)
        stem = f"{args.task}-{name}"  # task_id must stay: it has to match executable_spec.task_id
        for key, room in rooms.items():
            p["executable_spec"]["world"]["containers"][key]["room"] = room
        data = (json.dumps(p, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
        path = out / f"{stem}.taskpack.json"
        path.write_bytes(data)
        sha = "sha256:" + hashlib.sha256(data).hexdigest()
        cmd = rg.launcher(args.iw, "simulator") + ["run", "--taskpack", str(path), "--taskpack-sha256", sha,
                                                   "--prepare-task", "--no-render", "--gpu", "0"]
        log = out / f"{stem}.log"
        t0 = time.time()
        with open(out / f"{stem}.json", "w") as so, open(log, "w") as se:
            rc = subprocess.call(cmd, stdout=so, stderr=se, cwd=args.iw,
                                 env=dict(rg.ENV, INTERACTIVEWORLD_OUTPUT_DIR=str(out / "work")))
        err = rg.log_error(log)
        report[name] = {"rc": rc, "seconds": round(time.time() - t0), "rooms": rooms, "error": err}
        print(f"{name:18} rc={rc} {report[name]['seconds']}s {'BUILT' if rc == 0 else (err or '')[:200]}", flush=True)
    (out / "report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
