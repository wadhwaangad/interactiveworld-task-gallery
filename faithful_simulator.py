"""Run the release's launch/simulator.py, but let --action carry the runtime's full command grammar.

    <ISAAC_PYTHON> faithful_simulator.py --iw C:\\iw\\InteractiveWorld run --taskpack ... --action ...

The oracle-verbal runtime executes oracle commands exactly as taskpack_interaction._render_command
writes them, e.g. "[PutOn] <item_knife> (1) <surf_tool> (1) @place_spot=0.0:0.0" or
"[PutIn] <part_1> (1) <unit_a> (1) <unit_a_space2> (0)". The public Simulator.step() validates
through Action.parse, which rejects @place_spot and instance 0, so the CLI cannot replay them,
and dropping them changes what runs (a different drop spot, NO_FREE_PLACEMENT in a bag).

This wrapper changes nothing in the release. It patches Simulator.step so that only commands carrying
those two forms go through Simulator._step(validate_action=False), the same unvalidated path that
the task's own prologue uses; the server's command grammar parses them. Then it runs
launch/simulator.py unchanged.
"""
import re
import runpy
import sys
from pathlib import Path

_RUNTIME_ONLY = re.compile(r"@place_spot=|\(0\)")


def main():
    argv = sys.argv[1:]
    if len(argv) < 2 or argv[0] != "--iw":
        raise SystemExit("usage: faithful_simulator.py --iw <InteractiveWorld> <simulator.py args...>")
    iw = Path(argv[0 + 1]).resolve()
    sys.path.insert(0, str(iw))
    import simulator.api as api

    original = api.Simulator.step

    def step(self, action, *, trace_event=None):
        if isinstance(action, str) and _RUNTIME_ONLY.search(action):
            return self._step(action, validate_action=False, track_action=True, trace_event=trace_event)
        return original(self, action, trace_event=trace_event)

    api.Simulator.step = step
    sys.argv = [str(iw / "launch/simulator.py")] + argv[2:]
    runpy.run_path(str(iw / "launch/simulator.py"), run_name="__main__")


if __name__ == "__main__":
    main()
