#!/bin/bash
set -e

# 원본 이미지의 entrypoint.sh는 러너 설치 폴더(WORKDIR)에서 ./config.sh처럼
# 상대경로로 실행되게 되어 있다. 지금 있는 위치(=컨테이너 시작 시 WORKDIR)를
# 기억해뒀다가, cron을 띄운 뒤 다시 그 자리로 돌아가서 원본 entrypoint를 이어받는다.
RUNNER_HOME="$(pwd)"

: "${ACCESS_TOKEN:?ACCESS_TOKEN 환경변수가 필요합니다 (러너 등록 + 워크플로 dispatch 겸용)}"
: "${REPO_URL:?REPO_URL 환경변수가 필요합니다 (예: https://github.com/Murianwind/ev_charger_map)}"

# cron은 로그인 셸이 아니라 환경변수를 못 물려받는다. trigger_workflow.sh가
# GitHub API로 워크플로를 dispatch할 때 필요한 값들을 파일로 내보내둔다.
# (실제 데이터 갱신은 이 컨테이너가 아니라, 이 컨테이너가 러너로 등록해둔
# GitHub Actions 워크플로 쪽에서 실행된다 — EV_SERVICE_KEY도 거기서
# GitHub Secrets로 넘어가지 여기선 필요 없다.)
{
  echo "ACCESS_TOKEN=${ACCESS_TOKEN}"
  echo "REPO_URL=${REPO_URL}"
} > /etc/environment

echo "[scheduler] cron 시작 (10분마다 상태 갱신 워크플로 dispatch, 매일 04:00 KST 지역 갱신 워크플로 dispatch)"
cron

echo "[runner] GitHub Actions 러너 시작"
cd "$RUNNER_HOME"
exec /entrypoint.sh ./run.sh
