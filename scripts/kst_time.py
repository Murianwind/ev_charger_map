"""KST(한국 표준시) 관련 유틸리티. 여러 스크립트에서 공통으로 쓴다."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


def now_kst_iso():
    return now_kst().isoformat(timespec="seconds")
