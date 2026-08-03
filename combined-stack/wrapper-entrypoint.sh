#!/bin/bash
set -e

# 원본 이미지의 entrypoint.sh는 러너 설치 폴더(WORKDIR)에서 ./config.sh처럼
# 상대경로로 실행되게 되어 있다. 저장소 클론 작업을 위해 디렉터리를 옮겨다니기
# 전에, 지금 있는 위치(=컨테이너 시작 시 WORKDIR)를 기억해뒀다가 나중에 되돌아온다.
RUNNER_HOME="$(pwd)"

: "${ACCESS_TOKEN:?ACCESS_TOKEN 환경변수가 필요합니다 (러너 등록 + git push 겸용)}"
: "${REPO_URL:?REPO_URL 환경변수가 필요합니다 (예: https://github.com/Murianwind/ev_charger_map)}"
: "${EV_SERVICE_KEY:?EV_SERVICE_KEY 환경변수가 필요합니다}"

# REPO_URL(예: https://github.com/OWNER/REPO)에서 토큰이 포함된 clone/push용 remote를 만든다.
STRIPPED="${REPO_URL#https://}"
GIT_REMOTE="https://${ACCESS_TOKEN}@${STRIPPED}.git"

if [ ! -d /repo/.git ]; then
  echo "[scheduler] 저장소 클론 중..."
  git clone "$GIT_REMOTE" /repo
fi

cd /repo
git config user.name "home-scheduler"
git config user.email "home-scheduler@local"
git remote set-url origin "$GIT_REMOTE"

# cron 작업은 로그인 셸이 아니라 환경변수를 못 물려받는다.
# /etc/environment에 적어두고, crontab 항목에서 `. /etc/environment`로 불러온다.
{
  echo "EV_SERVICE_KEY=${EV_SERVICE_KEY}"
  echo "EV_STATUS_PERIOD_MIN=60"
} > /etc/environment

echo "[scheduler] cron 시작 (매시간 상태 갱신, 매일 04:00 KST 전체 갱신)"
cron

echo "[runner] GitHub Actions 러너 시작"
cd "$RUNNER_HOME"
exec /entrypoint.sh ./run.sh
