#!/usr/bin/env python3
"""Predict, without Isaac, whether the world builder can site a TaskPack's containers and supports.

    python -X utf8 preflight_siting.py taskpacks/pack/PACK-BEACH-HOLIDAY.taskpack.json [...]

Runs the release's own offline predictors (task_world_builder.predict_siting / predict_staging) on
scene JSON and bake-cache geometry. Room layout failures such as "cannot site declared multi-room
layout" then cost seconds instead of a ten-minute simulator launch.
"""
import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

import run_gallery as rg

HERE = Path(__file__).resolve().parent


def predict(pack, seed=0):
    from simulator.environment.runtime_builder_spec import register_runtime_builder_spec
    from simulator.interaction.task_runtime import builder_spec_from_taskpack
    from simulator.physical_world import task_world_builder as twb
    spec, digest = builder_spec_from_taskpack(pack)
    register_runtime_builder_spec(f"spec:{pack['task_id']}", spec, digest)
    try:
        noise = io.StringIO()
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            recipe = twb.recipe_for(pack["task_id"])
            out = {}
            for name, fn in (("siting", twb.predict_siting), ("staging", twb.predict_staging)):
                try:
                    ok, why = fn(recipe, seed)
                    out[name] = (ok, why)
                except Exception as exc:  # a predictor that raises is a prediction too
                    out[name] = (False, f"{type(exc).__name__}: {exc}")
        return out
    finally:
        twb.clear_runtime_spec()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("packs", nargs="+", type=Path)
    ap.add_argument("--iw", type=Path, default=Path(r"C:\iw\InteractiveWorld"))
    ap.add_argument("--env", type=Path, default=Path(r"C:\iw\assets\env.ps1"))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rg.load_env_file(args.env)
    os.environ.update(rg.ENV)
    sys.path.insert(0, str(args.iw))
    bad = 0
    for path in args.packs:
        pack = json.loads(path.read_text(encoding="utf-8"))
        res = predict(pack, args.seed)
        for name, (ok, why) in res.items():
            bad += ok is False
            mark = "ok  " if ok else "n/a " if ok is None else "FAIL"
            print(f"{mark} {name:8} {pack['task_id']:28} {str(why)[:600]}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
