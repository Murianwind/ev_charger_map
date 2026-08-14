FROM myoung34/github-runner:latest

# python3/git은 이제 이 컨테이너가 아니라 GitHub Actions 워크플로(러너가
# 받아서 실행) 쪽에서 setup-python/checkout이 알아서 준비해준다.
# 이 컨테이너는 cron으로 워크플로를 dispatch하고 러너 상태를 확인만 하면
# 되므로 curl(API 호출)과 jq(JSON 파싱)만 있으면 된다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron curl jq \
    && rm -rf /var/lib/apt/lists/*

COPY crontab /etc/cron.d/ev-charger-cron
COPY trigger_workflow.sh /repo_scripts/trigger_workflow.sh
COPY check_runner_health.sh /repo_scripts/check_runner_health.sh
COPY wrapper-entrypoint.sh /wrapper-entrypoint.sh

RUN chmod +x /repo_scripts/trigger_workflow.sh /repo_scripts/check_runner_health.sh /wrapper-entrypoint.sh \
    && chmod 0644 /etc/cron.d/ev-charger-cron \
    && touch /var/log/cron.log

ENTRYPOINT ["/wrapper-entrypoint.sh"]
