#!/bin/bash
set -e

# run_full.sh와 동시 실행되지 않도록 같은 잠금 파일을 공유한다.
exec 200>/tmp/repo.lock
flock -w 300 200 || { echo "다른 작업이 저장소 사용 중, 대기 시간 초과로 종료"; exit 1; }

cd /repo
git pull --rebase
python3 scripts/fetch_status.py
git add docs/data/chargers.geojson
git diff --cached --quiet || git commit -m "chore: charger status delta update (home scheduler)"
git push
