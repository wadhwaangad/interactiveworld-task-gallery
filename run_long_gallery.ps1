# Long-horizon gallery: GPU runs, one simulator at a time. Resumable: a finished layer is skipped.
# Roughly 20-25 hours in total; each block can be run on its own.

# 1. Cooking: oracle replay + video, then oracle-verbal.
python -u run_gallery.py --only ORCHESTRATE-46000 ORCHESTRATE-44001 ORCHESTRATE-28005 GUIDE-99502 ORCHESTRATE-107002 GUIDE-108005 GUIDE-87017 ORCHESTRATE-14003 --layers check story verbal

# 2. Packing (release) and the cleaning chore.
python -u run_gallery.py --only GUIDE-102000 GUIDE-110011 GUIDE-109009 GUIDE-14015 ASK-14011 ASK-13000 FIND-97003 GUIDE-14010 GUIDE-99806 GUIDE-17001 --layers check story verbal

# 3. The five packing ports, rebuilt (living-room support rebound): old results are stale, so --force.
python -u run_gallery.py --only PACK-BEACH-HOLIDAY PACK-GYM-WEEKEND PACK-WEEKEND-TRIP PACK-WINTER-VISIT PACK-WORK-TRIP --layers check story verbal --force

# 4. Reworded GUIDE tasks: same world and actions as their originals, so only oracle-verbal is new.
#    (The originals' oracle-verbal is predicted to stall by preflight_guide.py; it is not run.)
python -u run_gallery.py --only GUIDE-14004-REWORDED GUIDE-17001-REWORDED --layers verbal

# 5. Publish copy.
python export_site.py
