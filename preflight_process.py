"""Offline check that a perfect oracle run can satisfy each task's process requirements (no simulator).

    python -X utf8 preflight_process.py [--iw C:\\iw\\InteractiveWorld]

oracle-verbal's scripted human executes runtime.oracle_commands verbatim, including any
@place_spot. The runtime then requires completion_contract.required_successful_commands,
required_command_sequences and forbidden_before to hold over the successful commands. This feeds
the oracle commands in as if every one succeeded and asks the runtime's own
process_requirements_met(). A task that fails here cannot reach strict_success under oracle-verbal
on any machine, however well the physics goes.
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
        if spec.family == "WATCH":
            continue  # WATCH scores interventions against the default plan; not modelled here
        sess = ti.TaskPackInteractionSession(spec)
        observed = [sess._normalized_process_command(c) for c in spec.oracle_commands]  # as note_step()
        sess._successful_process_commands = list(observed)
        cc = spec.completion_contract
        unmatched = [c for c in cc.get("required_successful_commands", ())
                     if not any(sess._process_commands_equivalent(o, str(c)) for o in observed)]
        broken_seq = [list(s) for s in cc.get("required_command_sequences", ())
                      if not sess._process_command_subsequence_holds(s)]
        ok = sess.process_requirements_met()
        report[t["task_id"]] = {"ok": ok, "unmatched_required": unmatched, "broken_sequences": broken_seq}
        print(f"{'ok' if ok else 'BLOCKED':7} {t['task_id']:24}" + (f" unmatched: {unmatched[:2]}" if unmatched else ""))
    (HERE / "site/preflight_process.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
