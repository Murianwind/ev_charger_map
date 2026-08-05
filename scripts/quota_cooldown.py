"""일일 API 호출 한도 초과 시, 다음날 자정(KST)까지 재시도를 쉬는 쿨다운
상태를 관리한다. 특정 API를 몰라도 되는 범용 로직이라 여러 API에 재사용
가능하다 (지금은 gov_charger_api에서만 쓴다).

self-hosted 러너 컨테이너는 잡 사이에도 계속 떠있는 하나의 컨테이너라
/tmp가 실행 간에 유지된다(GitHub 호스팅 러너처럼 매번 새 VM이 아님) —
그래서 파일 하나로 상태를 넘길 수 있다.
"""
from datetime import datetime, timedelta

from kst_time import now_kst

COOLDOWN_FILE = "/tmp/.ev_quota_cooldown"


def in_cooldown():
    try:
        with open(COOLDOWN_FILE) as f:
            until_str = f.read().strip()
    except OSError:
        return False

    try:
        until = datetime.fromisoformat(until_str)
    except ValueError:
        return False
    return now_kst() < until


def start_cooldown():
    """다음날 자정(KST)까지 쿨다운을 걸고, 그 시각을 반환한다."""
    tomorrow_midnight = (now_kst() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with open(COOLDOWN_FILE, "w") as f:
        f.write(tomorrow_midnight.isoformat())
    return tomorrow_midnight
