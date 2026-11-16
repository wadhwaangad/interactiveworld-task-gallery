# Run after the video batch finishes (one simulator at a time).
# 0. Relabel WATCH oracle-verbal runs from the main batch as n/a (unsupported in this release).
python relabel_watch_verbal.py
# 1. Faithful replays and videos. These six tasks carry @place_spot or a (0) container-space index,
#    which the public simulator CLI rejects. run_gallery now goes through faithful_simulator.py.
python -u run_gallery.py --only ORCHESTRATE-99902 ORCHESTRATE-16013 NARRATE-87016 NARRATE-81009 ASK-13011 FIND-87004 --layers check story --force --frames-per-action 6
# 2. GUIDE-109009 and FIND-28003 fail an opening step on Windows physics (release Linux renders pass); try another seed.
python -u run_gallery.py --only GUIDE-109009 FIND-28003 --layers check --force --seed 1
# 3. PACK ports: the world builder cannot site three packing boxes in Rs_int living_room_0. Try other layouts.
python -u pack_layout_probe.py
