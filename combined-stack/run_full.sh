#!/bin/bash
set -e

# 이름은 run_full.sh지만, fetch_chargers.py는 이제 "그날 담당 지역만" 갱신하는
# 일일 로테이션 스크립트다 (16개 시도를 7일에 나눠 처리). 전국을 한 번에
# 다시 채우고 싶으면 FULL_SEED=1을 주고 수동 실행한다 (평소 cron에서는 안 씀).

# run_full.sh와 run_status.sh가 같은 /repo를 동시에 건드리면
# git pull --rebase가 충돌한다(특히 스케줄 시각이 겹치는 경우).
# 파일 잠금으로 항상 하나씩만 돌게 만든다.
exec 200>/tmp/repo.lock
flock -w 300 200 || { echo "다른 작업이 저장소 사용 중, 대기 시간 초과로 종료"; exit 1; }

cd /repo
git pull --rebase
python3 scripts/fetch_chargers.py
git add docs/data/chargers.geojson
git diff --cached --quiet || git commit -m "chore: daily regional charger data refresh (home scheduler)"
git push
