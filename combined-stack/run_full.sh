#!/bin/bash
set -e

# run_full.sh와 run_status.sh가 같은 /repo를 동시에 건드리면
# git pull --rebase가 충돌한다(특히 하루 1번 스케줄이 15분 스케줄과
# 겹치는 시각에). 파일 잠금으로 항상 하나씩만 돌게 만든다.
exec 200>/tmp/repo.lock
flock -w 300 200 || { echo "다른 작업이 저장소 사용 중, 대기 시간 초과로 종료"; exit 1; }

cd /repo
git pull --rebase
python3 scripts/fetch_chargers.py
git add docs/data/chargers.geojson
git diff --cached --quiet || git commit -m "chore: full charger data refresh (home scheduler)"
git push
