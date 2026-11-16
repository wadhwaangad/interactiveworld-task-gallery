# InteractiveWorld task gallery

**Site: https://wadhwaangad.github.io/interactiveworld-task-gallery/**

32 TaskPacks across all six InteractiveBench categories, a script that validates each one with the
oracle and renders its video, and a static website that shows the results.

| Source | Count | What |
| :--- | ---: | :--- |
| Bundled | 19 | Chosen from the 120 release tasks to cover every mechanic: recipes and cooking, appliances, aggregate goals, scanned documents, visual state events, blind-user narration, continuous watch, memory with decoys and nested containers. Copied byte-for-byte (LF), so they match the frozen manifest hashes. |
| Derived | 7 | New tasks built by `build_taskpacks.py` (below). |
| Reused | 6 | The earlier `PACK-*` packing ports, repaired (see "PACK ports"). |

Derived variants:

| Task | Type | What changes |
| :--- | :--- | :--- |
| `ASK-12802-CF-REPORT` | counterfactual document | The printed report says 1,860 kcal consumed. Same world and speech; the answer becomes the sugar cube. |
| `ASK-12802-CF-SPOKEN` | counterfactual speech | The person says lunch was 180 kcal. Same world and report; the answer becomes the sugar cube. |
| `ASK-12802-RETARGET` | retarget destination | The chosen snack goes to the living-room table (as in `examples/05_derive_taskpack.py`). |
| `WATCH-28008-ES` | multilingual | Same oven-door mistake; every spoken line, including the oracle warning, is in Spanish. |
| `WATCH-28008-LONGGAP` | memory horizon | Four extra steps between leaving the door open and pressing START. |
| `FIND-14015-MOVED` | memory update | The missing gift box is moved a second time; only its last observed place is correct. |
| `GUIDE-14004-REWORDED` | release-bug workaround | GUIDE-14004 with its third oracle line reworded so the handoff parser accepts it (see findings). |

Not possible: a no-fault "stay silent" WATCH control. The interaction compiler requires a WATCH task's
unguided plan to differ from the oracle plan.

## Results on this machine (RTX 4060 laptop, Windows)

Oracle replay (`check`) and oracle-verbal (`verbal`) for every task, 2026-11-14 and 15:

| Outcome | Tasks |
| :--- | :--- |
| Pass both | GUIDE-14011, ORCHESTRATE-99902, ORCHESTRATE-94001, NARRATE-14005, NARRATE-81009, ASK-12802, ASK-13011, FIND-87004, FIND-14015, ASK-12802-CF-REPORT, ASK-12802-CF-SPOKEN, ASK-12802-RETARGET, FIND-14015-MOVED, GUIDE-14004-REWORDED (14) |
| Pass replay; oracle-verbal n/a | WATCH-28008, WATCH-81020, WATCH-93005, WATCH-47003, WATCH-28008-ES, WATCH-28008-LONGGAP (6) |
| Release scorer/parser bug (any platform) | GUIDE-14004, NARRATE-87016, ASK-87022 |
| Pass replay; oracle-verbal fails on Windows physics | ORCHESTRATE-16013 (knife returns settle ~13 cm high and are refused) |
| Windows physics | GUIDE-109009 (order labels unreadable, 5.3 of 12 px; seeds 0 and 1), FIND-28003 (opening PutInside unstable in 2 of 4 launches; verbal passed) |
| World cannot be built | the 6 PACK ports (see below) |

Each task's card on the site shows the cause next to the failing layer.

### Release findings

All reproduced offline (no simulator) except the physics ones.

* **oracle-verbal cannot run WATCH tasks.** `run_taskpack.py` always uses the scripted Human under
  `--assistant oracle-verbal` (`human_policy` is hard-coded to `auto`, and no CLI flag changes it). The scripted Human only acts after the
  Assistant speaks, so it never performs a WATCH opening. The person stands still and the episode times
  out with `eval_valid=false`. The gallery records these as n/a. Testing WATCH with the oracle in the
  loop would need a model Human (an API key and a launcher that forces `human_policy="model"`).
* **GUIDE-14004:** the handoff parser reads "not the tomato" in the third oracle line as part of the
  Stir step, so the scripted person's "That's done" is never accepted. `preflight_guide.py` finds it;
  `GUIDE-14004-REWORDED` passes.
* **NARRATE-87016:** the oracle puts the glass and the bag inside with `@place_spot=0.0:0.0`, but the
  contract requires the plain `[PutInside]`, and `_process_commands_equivalent` forgives an optional
  spot only for PutOn. All actions succeed and the world goal is met, but strict success never comes.
* **ASK-87022:** the oracle sets the backpack down with `[PutOnFloor]`, but the contract requires a bare
  `[Drop]`, which nothing else matches.
* `patches/putinside-optional-spot.patch` fixes both scorer bugs (two rules in
  `_process_commands_equivalent`). It is **not applied** because it changes benchmark scoring. Both
  recorded runs meet their process requirements with it.

### PACK ports

The earlier `PACK-*` ports had never been built in this simulator. Fixed in `fix_pack`:
* added `story.source_contract` and non-empty `spoken_cues`;
* clamped garment scales of 0.44–0.45 to 0.5, since the builder only accepts scales in [0.5, 2.0].

Still open: the builder cannot site three `packing_box` bodies in Rs_int `living_room_0`, although each
fits alone. Release tasks never use more than one. `pack_layout_probe.py` tries spreading them across
rooms.

## 1. Build (any machine)

```bash
python build_taskpacks.py --iw ../InteractiveWorld [--env C:\iw\assets\env.ps1]
```

Writes `taskpacks/` (and `taskpacks/tasks.json` for `--taskpack-batch`) plus `site/catalog.{json,js}`.
Every pack is checked with:
* `TaskSpec.load`;
* the runtime's interaction compiler (`adapt_taskpack`);
* when the asset env is present, the world builder's recipe derivation (`recipe_for`). This catches
  role, body and scale errors without Isaac.

Room layout and physics are only checked in the simulator.

Two more offline checks predict oracle-verbal failures before any GPU time:

```bash
python -X utf8 preflight_guide.py     # GUIDE handoffs the parser would reject
python -X utf8 preflight_process.py   # process requirements a perfect oracle run cannot meet
```

Files are written with LF line endings. If you move them through git on Windows, disable
`core.autocrlf` for this folder or the pinned hashes break.

## 2. Validate and render

Three resumable layers per task, written to `site/results/<ID>/`:

| Layer | Command | Pass when |
| :--- | :--- | :--- |
| `check` | `simulator run --prepare-task` + oracle actions (WATCH: the full reference program unprepared, since `--prepare-task` refuses continuous-watch tasks) | `score.success`; for an unprepared WATCH replay whose goals are all baseline-excluded, every goal holding and no failed step |
| `story` | `simulator run` unprepared: the whole opening, then the oracle actions, with `--video` | it renders `story.mp4` (the site's video) |
| `verbal` | `run_taskpack --assistant oracle-verbal` (skipped for WATCH: n/a) | `native_taskpack_outcome.strict_success` |

Commands are rendered exactly as the runtime renders them (indices, `scalar_arg`, `@place_spot`). An
earlier build dropped `place_spot`, which made some replays diverge.

The public simulator CLI cannot take those commands as `--action`: `Action.parse` rejects
`@place_spot` and instance `(0)`. So on Windows the check and story layers run
`faithful_simulator.py`. It runs the release's `launch/simulator.py` unchanged. Only commands carrying
those forms are sent through `Simulator._step(validate_action=False)`, the same path the task's own
prologue uses. Six tasks need this: ORCHESTRATE-99902, ORCHESTRATE-16013, NARRATE-87016,
NARRATE-81009, ASK-13011 and FIND-87004. With it all six replay and render; the
ORCHESTRATE-16013 replay, which had failed with lossy commands, passes.

On this Windows machine `run_gallery.py` runs `launch\*.py` under `ISAAC_PYTHON` from
`C:\iw\assets\env.ps1`, against the Windows-patched clone at `C:\iw\InteractiveWorld`:

```powershell
python -u run_gallery.py                                  # all tasks, all layers
python -u run_gallery.py --only WATCH-28008-ES --force    # rerun one task
python -u run_gallery.py --only GUIDE-109009 --layers check --force --seed 1
.\rerun_after_batch.ps1                                   # the follow-ups listed in it
```

On Linux: `source ~/interactiveworld-assets/env.sh; python3 run_gallery.py --iw ~/InteractiveWorld`.

Three things had to be fixed for oracle-verbal on Windows:
* the frozen JSON under `C:\iw\InteractiveWorld\benchmark` was rewritten as LF (it failed its release
  hashes with CRLF);
* `benchmark\tasks\validate.py` needed an `as_posix()` fix;
* `PYTHONUTF8=1` is set for the subprocesses, because a cp1252 crash after the episode lost
  `results.jsonl`.

One simulator launch takes about 7–10 minutes, oracle-verbal up to 20.

## 3. View and publish

`python export_site.py` writes `docs/`, the public copy that GitHub Pages serves. It contains the page,
catalog, results, videos and TaskPacks, but no logs, raw simulator dumps or local paths. Commit `docs/`
and push to publish.


Open `site/index.html` directly, or serve the folder (`python -m http.server -d site`). It reads
`catalog.js` and `results.js`, plus the videos under `results/`.
