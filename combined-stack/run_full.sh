#!/bin/bash
set -e
cd /repo
git pull --rebase
python3 scripts/fetch_chargers.py
git add docs/data/chargers.geojson
git diff --cached --quiet || git commit -m "chore: full charger data refresh (home scheduler)"
git push
