# InteractiveWorld long-horizon gallery

**Site: https://wadhwaangad.github.io/interactiveworld-task-gallery/**

28 long cooking, packing and household TaskPacks, a script that validates each one with the oracle and
renders its video, and a static site that shows the results, longest tasks first.

| Theme | Tasks | Oracle steps |
| :--- | :--- | :--- |
| Cooking (11) | ORCHESTRATE-46000, -99902, -44001, -28005, -16013, -107002, -14003; GUIDE-99502, -108005, -87017, -14004 (+ GUIDE-14004-REWORDED) | 15–45 |
| Packing (14) | GUIDE-102000, -109009, -110011, -14015, -14010, -99806; ASK-14011, ASK-13000; FIND-97003; PACK-BEACH-HOLIDAY, -GYM-WEEKEND, -WEEKEND-TRIP, -WINTER-VISIT, -WORK-TRIP | 13–29 |
| Chores (1) | GUIDE-17001 (+ GUIDE-17001-REWORDED) | 32 |

The bundled tasks are the release's longest cooking and packing tasks by oracle length. They are copied
byte-for-byte (LF), so they match the frozen manifest hashes; they come from
[facebookresearch/InteractiveWorld](https://github.com/facebookresearch/InteractiveWorld) (CC BY-NC 4.0).
`PACK-*` are the earlier packing ports, repaired (below). The two `-REWORDED` tasks change only oracle
lines that the release's handoff parser rejects; they share their original's world, actions and video.

The earlier one-of-each-mechanic gallery (WATCH, NARRATE, counterfactual and multilingual variants) is
in git history; its builders are still in `build_taskpacks.py`.

## What a task has to pass

| Stage | Where | Passes when |
| :--- | :--- | :--- |
| Static | `build_taskpacks.py`, offline | `TaskSpec.load` accepts it, the interaction compiler (`adapt_taskpack`) compiles it, and the world builder derives a recipe (roles, bodies, scales) |
| Siting | `preflight_siting.py`, offline | the release's `predict_siting` / `predict_staging` can lay the containers, supports and stands out in the scene |
| Handoffs | `preflight_guide.py`, offline | the runtime's parser accepts "That's done" after every GUIDE instruction's chunk of actions |
| Process | `preflight_process.py`, offline | a perfect oracle run meets the contract's process requirements |
| Oracle replay (`check`) | simulator | after `--prepare-task`, the oracle actions leave the world in the goal state: every goal predicate holds and no prohibition is broken (`score.success`) |
| Video (`story`) | simulator | the opening plus the oracle actions, unprepared, render `story.mp4` |
| Oracle-verbal (`verbal`) | simulator + interaction runtime | scripted oracle advice and a scripted person reach `strict_success`: world goal met, process requirements met, verification points met, and the Assistant declares done |

## Release findings

* **Handoff parser.** GUIDE-14004 ("not the tomato") and GUIDE-17001 ("not on the electronics or paper",
  and a line that omits returning the cloth) stall under oracle-verbal. Spelling out a wipe ("wipe the mug
  with the blue sponge") parses correctly but is still rejected by the completion matcher.
* **Process scoring.** `_process_commands_equivalent` forgives an optional `@place_spot` only for PutOn,
  and a required bare `[Drop]` matches only itself (found on NARRATE-87016 and ASK-87022 in the earlier
  gallery). `patches/putinside-optional-spot.patch` fixes both. It is **not applied**, because it changes
  benchmark scoring.
* **The public CLI cannot replay runtime commands.** `Action.parse` rejects `@place_spot` and container
  instance `(0)`. `faithful_simulator.py` sends only those commands through `Simulator._step(validate_action=False)`,
  the path the task's own prologue uses. With it, the ORCHESTRATE-16013 replay passes.
* **oracle-verbal cannot run WATCH tasks.** The Human is always scripted under `--assistant oracle-verbal`,
  and the scripted Human only acts after the Assistant speaks.
* **Windows physics.** GUIDE-109009's order labels stay unreadable (5.3 of 12 px). ORCHESTRATE-16013's
  knife returns settle about 13 cm high under oracle-verbal.

### PACK ports

They never built. The error blamed the packing boxes, but the release's offline siting predictor
(`preflight_siting.py`) found the real cause. The person's stand at Rs_int's living-room
`breakfast_table`, among five chairs, is never on walkable floor, so `_layout_ok` rejected every layout.
`fix_pack` rebinds that support to the room's `bottom_cabinet`. It also:
* restores `story.source_contract` and `spoken_cues`;
* clamps garment scales to [0.5, 2.0].

PACK-MOVE-OUT is left out because no room layout of Rs_int holds its five boxes.

## 1. Build and check (any machine with the asset env)

```bash
python build_taskpacks.py --iw ../InteractiveWorld [--env C:\iw\assets\env.ps1]
python -X utf8 preflight_siting.py taskpacks/*/*.json
python -X utf8 preflight_guide.py
python -X utf8 preflight_process.py
```

`build_taskpacks.py` writes `taskpacks/` (and `taskpacks/tasks.json` for `--taskpack-batch`) plus
`site/catalog.{json,js}`. On Windows, set `INTERACTIVEWORLD_GENERATED_LABEL_CACHE` to an absolute
directory first. Files are written with LF; keep `core.autocrlf` off for this folder, or the pinned
hashes break.

## 2. Validate and render (GPU)

```powershell
.\run_long_gallery.ps1                                    # everything, resumable (~20-25 h)
python -u run_gallery.py --only GUIDE-102000 --force      # one task, all layers
```

Each layer writes `site/results/<ID>/`. On Windows, `run_gallery.py` runs `launch\*.py` under
`ISAAC_PYTHON` from `C:\iw\assets\env.ps1`, against the Windows-patched clone at `C:\iw\InteractiveWorld`.
The simulator goes through `faithful_simulator.py`. On Linux: `source ~/interactiveworld-assets/env.sh;
python3 run_gallery.py --iw ~/InteractiveWorld`.

Windows fixes needed for oracle-verbal:
* the frozen JSON under `benchmark\` rewritten as LF;
* an `as_posix()` fix in `benchmark\tasks\validate.py`;
* `PYTHONUTF8=1` for the subprocesses.

## 3. View and publish

Open `site/index.html`, or serve it with `python -m http.server -d site`.

`python export_site.py` writes `docs/`, the public copy GitHub Pages serves. It has the page, catalog,
results, videos and TaskPacks, but no logs, raw simulator dumps or local paths. Commit `docs/` and push.
