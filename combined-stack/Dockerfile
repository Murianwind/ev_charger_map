FROM myoung34/github-runner:latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron python3 \
    && rm -rf /var/lib/apt/lists/*

COPY crontab /etc/cron.d/ev-charger-cron
COPY run_full.sh /repo_scripts/run_full.sh
COPY run_status.sh /repo_scripts/run_status.sh
COPY wrapper-entrypoint.sh /wrapper-entrypoint.sh

RUN chmod +x /repo_scripts/run_full.sh /repo_scripts/run_status.sh /wrapper-entrypoint.sh \
    && chmod 0644 /etc/cron.d/ev-charger-cron \
    && crontab /etc/cron.d/ev-charger-cron \
    && touch /var/log/cron.log

ENTRYPOINT ["/wrapper-entrypoint.sh"]
