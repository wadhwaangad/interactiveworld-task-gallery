# Non-Markov variants: oracle replay + video, then oracle-verbal. Resumable; about 4 hours.
# Their controls (the base tasks) already have results.
python -u run_gallery.py --only GUIDE-108005-NM ORCHESTRATE-28005-NM GUIDE-110011-NM GUIDE-102000-NM --layers check story
python -u run_gallery.py --only GUIDE-108005-NM ORCHESTRATE-28005-NM GUIDE-110011-NM GUIDE-102000-NM --layers verbal
python export_site.py
