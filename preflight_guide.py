"""Offline check of the GUIDE handoff rule that oracle-verbal depends on (no simulator needed).

    python -X utf8 preflight_guide.py [--iw C:\\iw\\InteractiveWorld]

For GUIDE tasks the scripted Human says "That's done. What should I do next?" after each oracle
chunk, and the runtime only accepts it if its instruction parser judges the chunk's commands to
complete the spoken instruction. If it does not, the oracle never speaks again and the episode
runs out of ticks. This replays that exact check for every oracle chunk.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iw", type=Path, default=Path(r"C:\iw\InteractiveWorld"))
    args = ap.parse_args()
    sys.path.insert(0, str(args.iw))
    from simulator.interaction import taskpack_interaction as ti

    openings = json.loads((args.iw / "benchmark/tasks/interaction_openings.json").read_text(encoding="utf-8"))["tasks"]
    catalog = json.loads((HERE / "site/catalog.json").read_text(encoding="utf-8"))["tasks"]
    report = {}
    for t in catalog:
        pack = json.loads((HERE / "taskpacks" / t["file"]).read_text(encoding="utf-8"))
        spec = ti.adapt_taskpack(pack, openings)
        if spec.family != "GUIDE":
            continue
        sess = ti.TaskPackInteractionSession(spec)
        la, oa, ts = sess._guide_policy_grounding()
        anchors = list(spec.reference_dialogue_action_indices)
        cmds = list(spec.oracle_commands)
        stuck = []
        for i, instr in enumerate(spec.reference_dialogue):
            start = anchors[i] if anchors[i] is not None else 0
            later = [a for a in anchors if a is not None and a > start]
            end = min(later, default=len(cmds))
            chunk = cmds[start:end]
            if not chunk or end >= len(cmds):
                continue  # the last chunk ends the task; no handoff is needed
            ok = ti._successful_command_completes_claimed_instruction(
                "That's done. What should I do next?", chunk[-1], instr, chunk, (), oa, la, ts)
            if not ok:
                stuck.append({"dialogue_index": i, "instruction": instr, "chunk": chunk,
                              "units": [list(map(lambda x: sorted(x) if isinstance(x, set) else x, u))
                                        for u in ti._guide_instruction_completion_units(instr, oa, la, ts)]})
        report[t["task_id"]] = stuck
        print(f"{'STUCK' if stuck else 'ok':5} {t['task_id']:24}" +
              (f" at line {stuck[0]['dialogue_index'] + 1}: {stuck[0]['instruction'][:90]}" if stuck else ""))
    (HERE / "site/preflight_guide.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
