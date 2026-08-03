#!/bin/bash
set -e
cd /repo
git pull --rebase
python3 scripts/fetch_status.py
git add docs/data/chargers.geojson
git diff --cached --quiet || git commit -m "chore: charger status delta update (home scheduler)"
git push
