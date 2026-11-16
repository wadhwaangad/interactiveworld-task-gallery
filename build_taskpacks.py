"""Build the InteractiveWorld task gallery: curated bundled tasks, derived variants, fixed PACK ports.

    python build_taskpacks.py --iw ../InteractiveWorld [--packs ../packing-video-gallery/interactiveworld_taskpacks]

Writes taskpacks/*.taskpack.json (LF bytes, so the pinned SHA256 survives a copy to Linux),
taskpacks/tasks.json (a --taskpack-batch file) and site/catalog.json (what the website shows).
Every pack is checked with TaskSpec.load and with the runtime's own interaction compiler
(adapt_taskpack). Derived packs are compiled WITHOUT the openings catalog, so their opening
must be embedded. Physics is not checked here: run validate.sh on the GPU machine.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- curated bundled tasks
# (task_id, why it is in the gallery). Chosen to cover every mechanic the release uses.
CURATED = [
    ("GUIDE-14004", "Step-by-step cooking from a recipe card: cut, stir, cook, appliance on/off, visual state changes."),
    ("GUIDE-14011", "Guided appliance use: load, close and start a machine (running predicate)."),
    ("GUIDE-109009", "Sorting by capacity labels with aggregate goals and nested containers (27 actions)."),
    ("ORCHESTRATE-99902", "Plan an allergy-safe menu within 30 minutes from a scanned allergen sheet (45 actions)."),
    ("ORCHESTRATE-16013", "Long cutting plan with 12 visual state events (slices appear as the work proceeds)."),
    ("ORCHESTRATE-94001", "Route planning from a printed floor map across Rs_int."),
    ("NARRATE-87016", "Blind user: the Human gets no images; the Assistant describes a kitchen clean-up."),
    ("NARRATE-14005", "Blind user: orient (TurnAround) and pick up the right object by description."),
    ("NARRATE-81009", "Blind user: wipe a surface and place objects; a visual state event marks the clean."),
    ("ASK-12802", "Numeric decision across time: a report, a spoken lunch and three package labels."),
    ("ASK-13011", "Decision from 15 scanned receipts and price lists (164-tick budget)."),
    ("ASK-87022", "Spatial decision: place an object near a target on the floor (near predicate)."),
    ("WATCH-28008", "Continuous watch: the oven door was left open off-screen; stop START until it is closed."),
    ("WATCH-81020", "Continuous watch with an interruption: a phone call while an appliance is on."),
    ("WATCH-93005", "Continuous watch: a Confirm step the person must not skip."),
    ("WATCH-47003", "Continuous watch at the exit: check the departure board before leaving."),
    ("FIND-87004", "Memory: where was the red cola left before a seated phone call?"),
    ("FIND-14015", "Memory with identical decoys: which of two gift boxes was left behind?"),
    ("FIND-28003", "Memory across nested containers in a two-floor house."),
]


# ---------------------------------------------------------------- small helpers
def cmd_text(c):
    """Render a structured command exactly as simulator/taskpack_support/runtime_adapter.py does.

    indices, scalar_arg and place_spot all change what runs; e.g. ORCHESTRATE-16013 pins every
    knife return to @place_spot=0.0:0.0, and dropping it lets the planner pick a different spot.
    """
    args = c["args"]
    attach = c["verb"].upper() in {"ASSEMBLE", "ATTACH", "INSTALL"}
    space = c["verb"].upper() in {"PUTIN", "PUTINSIDE"}  # as taskpack_interaction._render_command
    idx = c.get("indices") or [0 if (attach and i in {1, 3}) or (space and i == 2) else 1
                               for i in range(len(args))]
    out = f"[{c['verb']}]" + "".join(f" <{a}> ({idx[i]})" for i, a in enumerate(args))
    if c.get("scalar_arg") is not None:
        out += " " + str(c["scalar_arg"])
    if c.get("place_spot") is not None:
        u, v = (float(x) for x in c["place_spot"])
        out += f" @place_spot={u!r}:{v!r}"
    return out


def parse_cmd(text):
    m = re.fullmatch(r"\[(\w+)\]((?:\s*<[^>]+>\s*\(\d+\))*)", text.strip())
    if not m:
        raise ValueError(f"cannot parse command {text!r}")
    return {"verb": m.group(1), "args": re.findall(r"<([^>]+)>", m.group(2))}


def effects(c):
    v, a = c["verb"], c["args"]
    if v == "Walk":
        return [{"op": "at", "subject": "human", "target": a[0]}]
    if v == "Grab":
        return [{"op": "held", "subject": a[0]}]
    if v in ("PutInside", "PutIn"):
        return [{"op": "inside", "subject": a[0], "target": a[1]}]
    return []


def replace_strings(node, pairs, skip=()):
    """Replace substrings in every string under node; `skip` lists dict keys left untouched."""
    if isinstance(node, dict):
        return {k: (v if k in skip else replace_strings(v, pairs, skip)) for k, v in node.items()}
    if isinstance(node, list):
        return [replace_strings(v, pairs, skip) for v in node]
    if isinstance(node, str):
        for old, new in pairs:
            node = node.replace(old, new) if not isinstance(old, re.Pattern) else old.sub(new, node)
        return node
    return node


def retoken(node, old, new):
    """Swap an object key used as a whole token (item_2 -> item_3) in every string and list."""
    return replace_strings(node, [(re.compile(rf"\b{re.escape(old)}\b"), new)])


class Ctx:
    def __init__(self, iw: Path):
        self.iw = iw
        sys.path.insert(0, str(iw))
        manifest = json.loads((iw / "benchmark/tasks/manifest.json").read_text(encoding="utf-8"))
        self.rows = {r["task_id"]: r for r in manifest["tasks"]}
        self.openings = json.loads((iw / "benchmark/tasks/interaction_openings.json").read_text(encoding="utf-8"))["tasks"]

    def path(self, tid):
        return self.iw / "benchmark/tasks" / self.rows[tid]["taskpack_path"]

    def lf_bytes(self, tid):
        return self.path(tid).read_bytes().replace(b"\r\n", b"\n")

    def pack(self, tid):
        return json.loads(self.lf_bytes(tid).decode("utf-8"))


def embed_opening(ctx, pack, base_id):
    """WATCH tasks keep their opening in the catalog; a derived pack must carry it itself."""
    story = pack["story"]
    if not isinstance(story.get("interaction"), dict):
        row = copy.deepcopy(ctx.openings[base_id])
        story["interaction"] = dict(row, opening=copy.deepcopy(row))
    return story["interaction"]


def opening_rows(inter):
    """Both copies of the opening: interaction-level keys and the nested `opening` (merged at runtime)."""
    return [d for d in (inter, inter.get("opening")) if isinstance(d, dict)]


def set_id(pack, new_id, base_id, kind, note):
    pack["task_id"] = pack["executable_spec"]["task_id"] = new_id
    pack["lineage"] = {"source": "interactiveworld-task-gallery/build_taskpacks.py", "base_task_id": base_id,
                       "variant": kind, "note": note}
    return pack


def insert_prologue(pack, at, new_actions):
    """Insert prologue actions before index `at`, keeping beats, evidence, utterances and program consistent."""
    story, spec = pack["story"], pack["executable_spec"]
    old = list(story["prologue"]["actions"])
    shift = lambda i: i if i < at else i + len(new_actions)  # noqa: E731
    story["prologue"]["actions"] = old[:at] + new_actions + old[at:]
    inter = story.get("interaction") or {}
    for d in opening_rows(inter):
        if "actions" in d:
            acts = d["actions"]
            d["actions"] = acts[:at] + new_actions + acts[at:]
        for u in d.get("utterances") or []:
            u["before_action_index"] = shift(u["before_action_index"])
    # prologue beats p000.. renumbered
    pro = [b for b in story["beats"] if b["phase"] == "before_turn0"]
    rest = [b for b in story["beats"] if b["phase"] != "before_turn0"]
    head = [b for b in rest if b["phase"] == "reset"]
    tail = [b for b in rest if b["phase"] != "reset"]
    new_beats = [{"id": "", "phase": "before_turn0", "actor": "human", "action": parse_cmd(a),
                  "effects": effects(parse_cmd(a)), "establishes": [], "requires": []} for a in new_actions]
    seq = pro[:at] + new_beats + pro[at:]
    rename = {}
    for i, b in enumerate(seq):
        if b["id"]:
            rename[b["id"]] = f"p{i:03d}"
        b["id"] = f"p{i:03d}"
    story["beats"] = head + seq + tail
    for e in story.get("evidence", []):
        e["source_beat_ids"] = [rename.get(x, x) for x in e.get("source_beat_ids", [])]
        if e.get("source_phase") == "opening" and isinstance(e.get("source_index"), int):
            e["source_index"] = shift(e["source_index"])
    task = (story.get("source_contract") or {}).get("task") or {}
    for f in task.get("fact_ledger") or []:
        if f.get("source_phase") == "opening" and isinstance(f.get("source_index"), int):
            f["source_index"] = shift(f["source_index"])
    # reference program = prologue + oracle when it was authored that way
    prog = spec["program"]["commands"]
    if [cmd_text(c) for c in prog[:len(old)]] == old:
        spec["program"]["commands"] = [parse_cmd(a) for a in story["prologue"]["actions"]] + prog[len(old):]
        b = spec["program"]["budget"]
        b["expanded_cmds"] = b["grammar_cmds"] = len(spec["program"]["commands"])
    pack["runtime"]["tick_budget"] += len(new_actions)
    return pack


def set_fact(pack, fid, statement):
    for e in pack["story"]["evidence"]:
        if e["id"] == fid:
            e["statement"] = statement
    for b in pack["story"]["beats"]:
        for e in b.get("establishes", []):
            if e["id"] == fid:
                e["statement"] = statement
    ac = pack["story"].get("assessment_contract") or {}
    ids = [e["id"] for e in pack["story"]["evidence"]]
    if "required_evidence" in ac and len(ac["required_evidence"]) == len(ids):
        ac["required_evidence"][ids.index(fid)] = statement


def set_dialogue(pack, say, index=0):
    r = pack["runtime"]
    r["dialogue"][index]["say"] = say
    did = r["dialogue"][index]["id"]
    for b in pack["story"]["beats"]:
        if b["id"] == did:
            b["say"] = say


# ---------------------------------------------------------------- derived variants
def ask_counterfactual(ctx, *, new_id, kind, note, edits, facts, premise, say, design):
    """ASK-12802 with the evidence changed so the sugar cube (item_3), not the syrup, is correct."""
    p = ctx.pack("ASK-12802")
    w = p["executable_spec"]["world"]
    w = edits(p) or w
    # retarget the answer: goal, oracle, policy, o-beats, report
    g = p["executable_spec"]["goal"]
    g["goals"] = g["answer_key"] = [{"pred": "on", "subject": "item_3", "target": "surf_3"}]
    p["runtime"] = retoken(p["runtime"], "item_2", "item_3")
    # default (unguided) commands still take the soda; keep them
    p["runtime"]["default_commands"] = ctx.pack("ASK-12802")["runtime"]["default_commands"]
    for b in p["story"]["beats"]:
        if b["id"].startswith("o"):
            b["action"]["args"] = ["item_3" if a == "item_2" else a for a in b["action"]["args"]]
    rep = p["executable_spec"]["report"]
    rep["sub_goals"][0].update(subject="item_3", target="surf_3")
    rep["sub_steps"] = ["on item_3 surf_3"]
    for fid, text in facts.items():
        set_fact(p, fid, text)
    set_dialogue(p, say)
    p["story"]["premise"] = premise
    p["executable_spec"]["meta"]["design"].update(premise=premise, assistant_must=design)
    p["story"]["assessment_contract"]["knowledge_constraints"] = [premise]
    return set_id(p, new_id, "ASK-12802", kind, note)


def cf_report(ctx):
    def edit(p):
        lab = p["executable_spec"]["world"]["labels"]["label_item_1"]["content"]
        lab["lines"][0] = "Calories|1,860 kcal|2,000 kcal|140 kcal"
        ac = p["story"]["assessment_contract"]
        ac["core_question"] = ac["core_question"].replace("110-calorie lunch", "110-calorie lunch (report now leaves 140 kcal)")
    return ask_counterfactual(
        ctx, new_id="ASK-12802-CF-REPORT", kind="counterfactual-document",
        note="Same world, same speech; only the printed report changes (1,860 kcal consumed), so the answer flips to the sugar cube.",
        edits=edit,
        facts={"fact_001": "The side-table report shows 1,860 calories consumed against a 2,000-calorie target, leaving 140 kcal.",
               "fact_003": "The adjusted remaining allowance is 30 kcal.",
               "fact_007": "The chocolate-syrup serving (45 kcal) exceeds the adjusted 30 kcal.",
               "fact_008": "The sugar cube (15 kcal) stays within the adjusted 30 kcal.",
               "fact_009": "The citrus-soda serving exceeds the adjusted 30 kcal.",
               "fact_010": "The sugar cube is the only serving within the allowance.",
               "fact_011": "The sugar cube is the highest-calorie eligible option."},
        premise=("The wearer checks a dated daily nutrition summary on a living-room side table. It shows 1,860 calories "
                 "consumed against a 2,000-calorie daily target, leaving 140 kcal. The wearer says that an additional "
                 "110-calorie lunch is not included in the report, so only 30 kcal remain. They take a brief phone call, then "
                 "inspect chocolate syrup and sugar cubes in the kitchen and a citrus soda at the drinks counter, and ask for "
                 "the highest-calorie serving that will not exceed the adjusted allowance. Syrup (45) and soda (120) are both "
                 "over; the assistant selects the sugar cube (15)."),
        say="Choose the sugar cube. The report leaves 140 calories, or 30 after your lunch. The syrup is 45 and the soda is 120, so both are over; the sugar cube is 15.",
        design="Read the edited report (140 kcal left), subtract the 110-calorie lunch, and select the sugar cube.")


def cf_spoken(ctx):
    def edit(p):
        inter = p["story"]["interaction"]
        for d in opening_rows(inter):
            for u in d.get("utterances") or []:
                u["say"] = u["say"].replace("about 110 calories for lunch", "about 180 calories for lunch")
        for cue in inter["information_contract"]["spoken_cues"]:
            cue["required_phrases"] = [x.replace("110 calories for lunch", "180 calories for lunch") for x in cue["required_phrases"]]
    return ask_counterfactual(
        ctx, new_id="ASK-12802-CF-SPOKEN", kind="counterfactual-speech",
        note="Same world, same report; only the spoken lunch changes (180 kcal), so the answer flips to the sugar cube.",
        edits=edit,
        facts={"fact_002": "The wearer says they already had an additional roughly 180-calorie lunch that is not included in the report.",
               "fact_003": "The adjusted remaining allowance is 40 kcal.",
               "fact_007": "The chocolate-syrup serving (45 kcal) exceeds the adjusted 40 kcal.",
               "fact_008": "The sugar cube (15 kcal) stays within the adjusted 40 kcal.",
               "fact_009": "The citrus-soda serving exceeds the adjusted 40 kcal.",
               "fact_010": "The sugar cube is the only serving within the allowance.",
               "fact_011": "The sugar cube is the highest-calorie eligible option."},
        premise=("The wearer checks a daily nutrition summary showing 1,780 of 2,000 calories, leaving 220 kcal, and says an "
                 "unlogged lunch was about 180 calories, so only 40 kcal remain. After a brief call they inspect chocolate "
                 "syrup, sugar cubes and a citrus soda and ask for the highest-calorie serving within the allowance. Syrup (45) "
                 "and soda (120) are over; the assistant selects the sugar cube (15)."),
        say="Choose the sugar cube. The report leaves 220 calories, but after your 180-calorie lunch only 40 remain. The syrup is 45 and the soda is 120, both over; the sugar cube is 15.",
        design="Use the spoken 180-calorie lunch (40 kcal left) and select the sugar cube.")


def retarget(ctx):
    """examples/05_derive_taskpack.py, reproduced: destination moves to the living-room table."""
    p = ctx.pack("ASK-12802")
    w = p["executable_spec"].pop("world")
    p = replace_strings(p, [(re.compile(r"\bsurf_3\b"), "surf_call"),
                            ("kitchen breakfast table", "living-room table"), ("breakfast table", "living-room table")])
    p["executable_spec"]["world"] = w
    return set_id(p, "ASK-12802-RETARGET", "ASK-12802", "retarget-destination",
                  "Same reasoning, destination moved to the living-room table (mirrors examples/05_derive_taskpack.py).")


WATCH_ES = {
    "prelude": "Hola, Asistente, estoy horneando. Vigila lo que hago y avísame si cometo un error.",
    "cues": ["Hola, Asistente", "Vigila lo que hago", "avísame si cometo un error"],
    "say": "Espera: la puerta del horno sigue abierta desde que metiste la tarta. Ciérrala antes de encender el horno.",
    "turn0": "La tarta ya está dentro. Voy a encender el horno.",
}


def watch_spanish(ctx):
    p = ctx.pack("WATCH-28008")
    inter = embed_opening(ctx, p, "WATCH-28008")
    for d in opening_rows(inter):
        d["prelude_say"] = WATCH_ES["prelude"]
        d["public_task_context"] = "La persona está horneando (la conversación es en español)."
        d["information_contract"] = {"spoken_cues": [{"id": "watch_request", "required_phrases": WATCH_ES["cues"]}]}
        for iv in d.get("watch_interventions") or []:
            iv["assistant_say"] = WATCH_ES["say"]
        d["human_task_context"] += " The person speaks only Spanish: say every utterance in Spanish."
    set_dialogue(p, WATCH_ES["say"])
    for b in p["story"]["beats"]:
        if b["id"] == "turn0":
            b["say"] = WATCH_ES["turn0"]
    p["story"]["assistant_goal"] = WATCH_ES["turn0"]
    set_fact(p, "fact_001", WATCH_ES["turn0"])
    return set_id(p, "WATCH-28008-ES", "WATCH-28008", "multilingual",
                  "Identical world and timing; every spoken line (person and oracle advice) is in Spanish.")


def watch_nofault(ctx):
    """Restraint control: the person closes the oven door themselves, so the right advice is none."""
    p = ctx.pack("WATCH-28008")
    inter = embed_opening(ctx, p, "WATCH-28008")
    insert_prologue(p, 7, ["[Close] <oven> (1)"])
    r = p["runtime"]
    r["dialogue"], r["dialogue_budget"] = [], 0
    r["oracle_commands"] = [{"verb": "TurnOn", "args": ["oven"]}]
    hp = r["human_policy"]
    hp["transitions"] = []
    hp["terminal_beats"] = ["h000"]
    p["story"]["beats"] = [b for b in p["story"]["beats"] if b["id"] not in ("assistant_intervention", "o000", "o001")]
    spec = p["executable_spec"]
    spec["program"]["commands"] = spec["program"]["commands"][:-2] + [{"verb": "TurnOn", "args": ["oven"]}]
    spec["program"]["budget"]["expanded_cmds"] = spec["program"]["budget"]["grammar_cmds"] = len(spec["program"]["commands"])
    for d in opening_rows(inter):
        d["watch_interventions"] = []
        cc = d["completion_contract"]
        cc.update(required_successful_commands=["[TurnOn] <oven> (1)"], required_command_sequences=[["[TurnOn] <oven> (1)"]],
                  forbidden_before=[])
        cc["verification_points"] = [v for v in cc["verification_points"] if v["kind"] != "intervention"]
    set_fact(p, "fact_003", "The pie was inserted and the wearer closed the oven door right after.")
    set_fact(p, "fact_005", "The oven door is closed; starting the oven is safe and no warning is needed.")
    premise = ("The wearer moves an oven glove to the pie table, opens the oven, loads an apple pie, closes the door, then "
               "walks to the cooling counter to press START. Nothing is wrong: a good assistant stays silent.")
    p["story"]["premise"] = premise
    spec["meta"]["design"].update(premise=premise, assistant_must="Stay silent; the oven door was closed.",
                                  anti_shortcut="An assistant that always warns about the oven door interrupts needlessly.")
    return set_id(p, "WATCH-28008-NOFAULT", "WATCH-28008", "restraint-control",
                  "Paired control for WATCH-28008: the door is closed in the prologue, so any warning is a false alarm.")


def watch_longgap(ctx):
    p = ctx.pack("WATCH-28008")
    embed_opening(ctx, p, "WATCH-28008")
    insert_prologue(p, 7, ["[Walk] <mitt_table> (1)", "[Wait]", "[Walk] <pie_table> (1)", "[Wait]"])
    set_fact(p, "fact_004", "After loading the pie the wearer walked to the living room, waited, came back via the pie "
                            "table and then to the cooling counter, so the open oven door was out of view for several steps.")
    premise = ("As WATCH-28008, but after loading the pie the wearer wanders into the living room and back before reaching "
               "the cooling counter, so the open oven door was last seen many steps earlier.")
    p["story"]["premise"] = premise
    p["executable_spec"]["meta"]["design"]["premise"] = premise
    return set_id(p, "WATCH-28008-LONGGAP", "WATCH-28008", "memory-horizon",
                  "Four extra prologue steps between the open door and START: a longer memory gap.")


def find_moved(ctx):
    """The missing gift box is moved a second time, to the coffee table where the call happens."""
    p = ctx.pack("FIND-14015")
    insert_prologue(p, 9, ["[Walk] <surf_original> (1)", "[Grab] <gift_target> (1)", "[Walk] <surf_phone> (1)",
                           "[PutOn] <gift_target> (1) <surf_phone> (1)", "[Walk] <surf_remote> (1)"])
    r = p["runtime"]
    r["oracle_commands"][0]["args"] = ["surf_phone"]
    for t in r["human_policy"]["transitions"]:
        if t["condition"].get("target") == "surf_original":
            t["condition"]["target"] = "surf_phone"
    for b in p["story"]["beats"]:
        if b["id"] == "o000":
            b["action"]["args"] = ["surf_phone"]
            b["effects"] = effects(b["action"])
    say = ("The other gift box is on the coffee table in the other living room. You first left it on the living-room "
           "table, then carried it to that coffee table before taking your call.")
    set_dialogue(p, say)
    set_fact(p, "fact_005", say)
    p["executable_spec"]["program"]["commands"][-4]["args"] = ["surf_phone"]
    premise = ("As FIND-14015, but after carrying the decoy box to the kitchen the wearer goes back, moves the remaining box "
               "to the coffee table in the second living room, and later answers the phone at that same table. The first "
               "remembered place (the living-room table) is now wrong; only the last observed placement is right.")
    p["story"]["premise"] = premise
    p["executable_spec"]["meta"]["design"]["premise"] = premise
    return set_id(p, "FIND-14015-MOVED", "FIND-14015", "memory-update",
                  "The target moves twice; recalling its first location fails, only the last observed location works.")


def guide_reworded(ctx):
    """GUIDE-14004 with its third oracle line reworded so the runtime's handoff parser accepts it.

    The release line says "...the flat top, not the tomato, is the Stir target", which the parser
    reads as a Stir involving the tomato; the executed Stir never matches, the scripted Human's
    "That's done" is rejected and oracle-verbal stalls until max_ticks (see preflight_guide.py).
    """
    p = ctx.pack("GUIDE-14004")
    set_dialogue(p, "Grab the spatula from the tool table, stir the cooktop with the spatula, and put the "
                    "spatula back on the tool table. Then cook the sliced tomato.", index=2)
    return set_id(p, "GUIDE-14004-REWORDED", "GUIDE-14004", "repaired-dialogue",
                  "Same recipe task; only the oracle's third instruction is reworded, because the release wording "
                  "stalls oracle-verbal (the parser reads 'not the tomato' as part of the Stir step).")


# watch_nofault is kept for reference but not built: the compiler requires a WATCH default plan that
# diverges from the oracle plan, so a no-fault restraint control cannot be expressed.
DERIVED = [cf_report, cf_spoken, retarget, watch_spanish, watch_longgap, find_moved, guide_reworded]


def fix_pack(ctx, pack):
    """Prior PACK ports dropped story.source_contract; the runtime needs its family to compile the interaction."""
    tmpl = ctx.pack("GUIDE-99806")["story"]["source_contract"]
    sc = {"base_task_id": "GUIDE-99806", "family": "GUIDE", "revision": tmpl.get("revision"),
          "grounding_contract": tmpl.get("grounding_contract"), "authorized_scope": tmpl.get("authorized_scope")}
    pack["story"]["source_contract"] = sc
    ask = pack["story"]["interaction"]["opening"]["handoff_say"]
    phrases = [x for x in ("Hey, Assistant", "one item at a time", "which box") if x in ask]
    pack["story"]["interaction"]["information_contract"] = {
        "spoken_cues": [{"id": "packing_request", "required_phrases": phrases}]}
    # The world builder only accepts object scales in [0.5, 2.0] (task_world_builder._bts_scale); the
    # ports shrank some garment piles to 0.44-0.45 to fit the boxes. Clamp to the nearest legal scale.
    clamped = []
    for key, row in pack["executable_spec"]["world"].get("objects", {}).items():
        if "scale" in row and not 0.5 <= float(row["scale"]) <= 2.0:
            clamped.append(f"{key} {row['scale']}->{min(2.0, max(0.5, float(row['scale'])))}")
            row["scale"] = min(2.0, max(0.5, float(row["scale"])))
    note = "interactiveworld-task-gallery: restored story.source_contract"
    pack.setdefault("lineage", {})["fixed_by"] = note + (f"; clamped scale {', '.join(clamped)}" if clamped else "")
    return pack


# ---------------------------------------------------------------- catalog for the site
FAMILY_CATEGORY = {"GUIDE": "Guidance", "ORCHESTRATE": "Planning", "NARRATE": "Accessibility", "ASK": "Decision",
                   "WATCH": "Prevention", "FIND": "Finding"}


def mechanics(p):
    es, r = p["executable_spec"], p["runtime"]
    w, g = es["world"], es["goal"]
    m = sorted({x["pred"] for x in g["goals"]})
    verbs = sorted({c["verb"] for c in r["oracle_commands"]})
    tags = []
    if r.get("public_preparation", {}).get("mode") == "continuous_watch":
        tags.append("continuous watch")
    if w.get("labels"):
        tags.append(f"{len(w['labels'])} document(s)")
    if r.get("visual_state_events"):
        tags.append(f"{len(r['visual_state_events'])} visual events")
    if g.get("aggregate_goals"):
        tags.append("aggregate goals")
    if (g.get("roster") or {}).get("nested_containers"):
        tags.append("nested containers")
    return {"predicates": m, "verbs": verbs, "tags": tags}


def replay_actions(p):
    """Actions for the deterministic oracle replay (validate.sh layer 1)."""
    watch = p["runtime"].get("public_preparation", {}).get("mode") == "continuous_watch"
    oracle = [cmd_text(c) for c in p["runtime"]["oracle_commands"]]
    inter = p["story"].get("interaction") or {}
    opening = (inter.get("opening") or {}).get("actions") or p["story"]["prologue"]["actions"]
    # check: how the benchmark prepares the task (--prepare-task cannot run continuous WATCH tasks)
    check = [cmd_text(c) for c in p["executable_spec"]["program"]["commands"]] if watch else oracle
    return {"prepare_task": not watch, "actions": check,
            # story: the whole opening then the oracle, unprepared, so the video shows what led up to the request
            "story_actions": list(opening) + oracle}


def entry(p, *, source, why, base=None, kind=None, file):
    s, r = p["story"], p["runtime"]
    fam = (s.get("source_contract") or {}).get("family") or p["executable_spec"]["meta"].get("family")
    inter = s.get("interaction") or {}
    opening = inter.get("opening") or inter
    utter = [u["say"] for u in opening.get("utterances") or []]
    if opening.get("prelude_say"):
        utter = [opening["prelude_say"]] + utter
    return {"task_id": p["task_id"], "family": fam, "category": FAMILY_CATEGORY.get(fam, fam), "source": source,
            "variant": kind, "base_task_id": base, "why": why, "scene": p["executable_spec"]["world"]["scene"],
            "premise": s["premise"], "request": s["assistant_goal"], "opening_utterances": utter,
            "prologue": s["prologue"]["actions"], "oracle_dialogue": [d["say"] for d in r["dialogue"]],
            "oracle_commands": [cmd_text(c) for c in r["oracle_commands"]],
            "goals": [f"{x['pred']}({x['subject']}, {x.get('target')})" for x in p["executable_spec"]["goal"]["goals"]],
            "tick_budget": r["tick_budget"], "replay": replay_actions(p), "file": file,
            "known_issue": KNOWN_ISSUES.get(p["task_id"]) or (PACK_ISSUE if p["task_id"].startswith("PACK-") else None), **mechanics(p)}


# Release behaviour found while running the gallery; shown on the site next to the task.
KNOWN_ISSUES = {
    "GUIDE-14004": ("oracle-verbal stalls in the release itself, on every platform: the handoff parser reads "
                    "'not the tomato' in the third oracle line as part of the Stir step, so the scripted "
                    "person's 'That's done' is rejected after Cook. See GUIDE-14004-REWORDED."),
    "NARRATE-87016": ("oracle-verbal cannot reach strict success in the release, on any platform: every action "
                      "succeeds and the world goal is met, but the oracle puts the glass and the bag inside with "
                      "@place_spot=0.0:0.0 while the contract requires the plain PutInside, and "
                      "_process_commands_equivalent only forgives an optional spot for PutOn. Reproduced offline "
                      "by preflight_process.py."),
    "ASK-87022": ("oracle-verbal cannot reach strict success in the release, on any platform: the backpack ends up "
                  "beside the parallel bars and the world goal is met, but the oracle sets it down with [PutOnFloor] "
                  "while the contract requires a bare [Drop], which no command but [Drop] itself matches. Predicted "
                  "offline by preflight_process.py before the run."),
    "ORCHESTRATE-16013": ("The oracle replay and the video pass once commands keep their @place_spot (the earlier "
                          "lossy rendering made the replay fail). Under oracle-verbal on this Windows machine the "
                          "2nd and 3rd knife returns to @place_spot=0.0:0.0 on the tool counter settle ~13 cm high "
                          "and are refused, so the guest-one instruction never completes."),
    "WATCH-93005": ("The reference program opens with [LookAt] <item_1> from the unprepared start pose, 5.3 m "
                    "away behind an armchair, so that read fails (0.1 px) in both the replay and the video; the "
                    "rest of the program runs and the goal is met. The release's Linux render reports no failed "
                    "action, so its prepared start is presumably nearer."),
    "FIND-28003": ("Flaky on this Windows machine: in two of four launches (seeds 0 and 1, prepared) the "
                   "opening's [PutInside] <mushrooms> <box> did not stay inside after three settle attempts "
                   "(UNSTABLE_AFTER_RELEASE), so the oracle replay stopped before the request; the oracle-verbal "
                   "launch and the video placed it and passed."),
    "GUIDE-109009": ("On this Windows machine the person cannot read any of the three order sheets in the "
                     "opening: lifted to the face, each ends up rolled in the hand and stays below the label "
                     "size the reader needs (order A: 9.2 px of 10 held, 5.3 px of 12 on the counter). The "
                     "prepared runs stop there; the video continues past the failed reads, so it shows them. "
                     "The release's own Linux render of this task passed. Seed 1 fails the same way."),
}
PACK_ISSUE = ("The world cannot be built yet: the builder cannot site three packing_box bodies in Rs_int "
              "living_room_0, although each fits alone (release tasks never use more than one). "
              "pack_layout_probe.py tries spreading them across rooms.")


# ---------------------------------------------------------------- main
def write_lf(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def check(pack, path, digest, openings):
    from simulator import TaskSpec
    from simulator.interaction.taskpack_interaction import adapt_taskpack
    spec = TaskSpec.load(path, expected_sha256=digest)
    adapt_taskpack(pack, openings)
    derive_world_recipe(pack)
    return spec


def derive_world_recipe(pack):
    """The world builder's recipe derivation (roles, bodies, scales), without Isaac.

    Needs the asset env (ISAAC asset root etc.), so it is skipped when that is not loaded. It catches
    build-rule errors such as an out-of-range object scale; room layout is decided later, on the stage.
    """
    import contextlib
    import io
    import os
    if not os.environ.get("ISAAC_PYTHON"):
        return
    from simulator.environment.runtime_builder_spec import register_runtime_builder_spec
    from simulator.interaction.task_runtime import builder_spec_from_taskpack
    from simulator.physical_world import task_world_builder as twb
    try:
        spec, digest = builder_spec_from_taskpack(pack)
        register_runtime_builder_spec(f"spec:{pack['task_id']}", spec, digest)
        with contextlib.redirect_stdout(io.StringIO()):
            twb.recipe_for(pack["task_id"])
    finally:
        twb.clear_runtime_spec()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iw", type=Path, default=HERE.parent / "InteractiveWorld")
    ap.add_argument("--packs", type=Path, default=HERE.parent / "packing-video-gallery/interactiveworld_taskpacks")
    ap.add_argument("--env", type=Path, default=Path(r"C:\iw\assets\env.ps1"),
                    help="asset env file; when present, packs are also run through the world recipe derivation")
    args = ap.parse_args()
    if args.env and args.env.exists():
        import os
        import run_gallery
        run_gallery.load_env_file(args.env)
        os.environ.update(run_gallery.ENV)
    ctx = Ctx(args.iw.resolve())
    out = HERE / "taskpacks"
    batch, catalog, failures = [], [], []

    def emit(pack, data, rel, openings, **meta):
        path = out / rel
        digest = write_lf(path, data)
        try:
            check(pack, path, digest, openings)
            status = "ok"
        except Exception as exc:  # report every failure, keep going
            status = f"FAIL {type(exc).__name__}: {exc}"
            failures.append((pack["task_id"], status))
        print(f"{status[:4]:4} {pack['task_id']:26} {rel}" + ("" if status == "ok" else f"\n     {status[:300]}"))
        batch.append({"task_id": pack["task_id"], "taskpack_path": rel, "taskpack_sha256": digest})
        catalog.append(dict(entry(pack, file=rel, **meta), sha256=digest, static_check=status))

    for tid, why in CURATED:
        data = ctx.lf_bytes(tid)
        assert "sha256:" + hashlib.sha256(data).hexdigest() == ctx.rows[tid]["taskpack_sha256"], tid
        emit(json.loads(data), data, f"bundled/{tid}.taskpack.json", ctx.openings, source="bundled", why=why)

    for fn in DERIVED:
        pack = fn(ctx)
        data = (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        lin = pack["lineage"]
        emit(pack, data, f"derived/{pack['task_id']}.taskpack.json", {}, source="derived", why=lin["note"],
             base=lin["base_task_id"], kind=lin["variant"])

    for path in sorted(args.packs.glob("PACK-*.taskpack.json")):
        pack = fix_pack(ctx, json.loads(path.read_text(encoding="utf-8")))
        data = (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        emit(pack, data, f"pack/{pack['task_id']}.taskpack.json", {}, source="reused",
             why=pack["executable_spec"]["meta"]["design"]["premise"], base="GUIDE-99806", kind="packing-port")

    (out / "tasks.json").write_bytes((json.dumps({"tasks": batch}, indent=2) + "\n").encode())
    site = HERE / "site"
    site.mkdir(exist_ok=True)
    (site / "catalog.json").write_bytes((json.dumps({"tasks": catalog}, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    # the page loads this with a <script> tag so it also works when opened from disk
    (site / "catalog.js").write_bytes(
        ("window.GALLERY_CATALOG = " + json.dumps({"tasks": catalog}, ensure_ascii=False) + ";\n").encode("utf-8"))
    print(f"\n{len(batch)} taskpacks, {len(failures)} static failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
