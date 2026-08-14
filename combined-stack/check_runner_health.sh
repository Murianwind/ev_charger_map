#!/bin/bash
# GitHub Runners API로 이 러너가 실제로 "online"인지 확인한다.
# 아니면(오프라인/응답없음) 디스코드로 알리고, 컨테이너를 정상 종료시켜
# docker의 restart 정책이 깨끗한 상태로 다시 띄우게 만든다.
#
# 도커 데스크탑이 재시작되면(윈도우 재부팅 등) 컨테이너가 종료 신호 없이
# 강제로 같이 죽어서, GitHub 쪽엔 "등록됨"으로 남고 컨테이너는 다시 뜨면서
# 재등록을 시도하다가 꼬이는 경우가 있다(Value cannot be null:
# 'configuredSettings'). 이걸 사람이 매번 Portainer에서 수동으로 재생성해줄
# 필요 없이 자동으로 감지/복구하기 위한 스크립트다.
set -e

: "${ACCESS_TOKEN:?ACCESS_TOKEN 환경변수가 필요합니다}"
: "${REPO_URL:?REPO_URL 환경변수가 필요합니다}"
: "${RUNNER_NAME:?RUNNER_NAME 환경변수가 필요합니다}"

REPO_PATH="${REPO_URL#https://github.com/}"

RESPONSE=$(curl -s -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO_PATH}/actions/runners")

STATUS=$(echo "$RESPONSE" | jq -r --arg name "$RUNNER_NAME" '.runners[] | select(.name==$name) | .status')

if [ "$STATUS" = "online" ]; then
  echo "[health] 러너 정상(online)"
  exit 0
fi

echo "[health] 러너 비정상(상태: ${STATUS:-확인불가}) — 재시작을 유도합니다"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  MESSAGE="⚠️ EV 충전지도 러너(${RUNNER_NAME})가 오프라인입니다 (상태: ${STATUS:-확인불가}). 컨테이너 재시작을 시도합니다."
  curl -s -X POST -H "Content-Type: application/json" \
    -d "$(jq -n --arg content "$MESSAGE" '{content: $content}')" \
    "$DISCORD_WEBHOOK_URL" > /dev/null || echo "[health] 디스코드 알림 전송 실패(무시하고 계속 진행)"
fi

# PID 1(entrypoint.sh)에게 정상 종료 신호를 보낸다. entrypoint.sh 자체에
# SIGTERM을 받으면 GitHub에서 러너를 먼저 정상적으로 등록 해제(deregister)한
# 뒤 종료하는 로직이 이미 있어서, 강제 종료보다 훨씬 깨끗하게 복구된다.
# 컨테이너가 종료되면 docker-compose의 restart: unless-stopped 정책이
# 다시 띄워주고, 그 시점에 새로 깨끗하게 등록을 시도한다.
kill 1
