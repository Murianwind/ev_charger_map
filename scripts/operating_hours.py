"""이용시간(useTime) 텍스트를 파싱해서 구조화된 운영시간 정보로 바꾼다.

프론트엔드가 "지금 이 충전소가 운영시간 안인지"를 판단할 수 있도록, 원본
자유 텍스트("09:00~18:00", "평일 09시~18시" 등)를 다음 형태로 정규화한다:

    {"kind": "always"}                                   # 24시간/상시
    {"kind": "daily", "start": 540, "end": 1080}          # 매일 같은 시간(분 단위, 자정=0)
    {"kind": "weekday_only", "start": 540, "end": 1080}   # 평일만(주말 언급 없음 -> 주말엔 숨김)
    {"kind": "weekday_weekend", "start": ..., "end": ..., "weekendStart": ..., "weekendEnd": ...}
    {"kind": "unknown"}                                   # 파싱 실패/빈 값 -> 항상 표시(안전)

start/end는 자정 기준 분(0~1439)이다. start > end면 자정을 넘기는(익일까지)
운영시간으로 본다(예: 22:00~06:00) — 프론트엔드가 이 경우를 감안해서 비교한다.
"""
import re

# "09:00~18:00" / "09시~18시" / "9:00 ~ 21:00" / "10:00:00~23:59:59"(초는 버림) 등을
# 폭넓게 잡는다. 시:분 구분자로 ":" 또는 "시"를 허용하고, 초 단위가 붙어있으면 무시한다.
_TIME_RANGE = re.compile(
    r"(\d{1,2})\s*[:시]\s*(\d{0,2})(?::\d{0,2})?\s*[-~]\s*(\d{1,2})\s*[:시]\s*(\d{0,2})(?::\d{0,2})?"
)

_WEEKDAY_WORDS = ("평일", "주중")
_WEEKEND_WORDS = ("주말", "토요일", "일요일", "공휴일")
_WEEKEND_EXCLUDED_WORDS = ("제외", "미운영", "미개방")
# "주중/주말 : 24시간"처럼 요일 구분 없이 병기된 경우 -> 평일 전용이 아니라 매일 적용.
_SAME_ALL_WEEK_PATTERN = re.compile(r"주중\s*/\s*주말")


def _to_minutes(hour_str, min_str):
    hour = int(hour_str) % 24
    minute = int(min_str) % 60 if min_str else 0
    return hour * 60 + minute


def _find_ranges(text):
    """텍스트 안의 모든 시간 범위를 (start_분, end_분) 튜플 리스트로 반환한다."""
    ranges = []
    for m in _TIME_RANGE.finditer(text):
        start = _to_minutes(m.group(1), m.group(2))
        end = _to_minutes(m.group(3), m.group(4))
        ranges.append((start, end))
    return ranges


def parse_use_time(text):
    """useTime 원본 텍스트를 구조화된 dict로 변환한다."""
    text = (text or "").strip()
    if not text:
        return {"kind": "unknown"}

    if "24시간" in text or text == "상시":
        return {"kind": "always"}

    if _SAME_ALL_WEEK_PATTERN.search(text):
        ranges = _find_ranges(text)
        if ranges:
            start, end = ranges[0]
            return {"kind": "daily", "start": start, "end": end}
        return {"kind": "unknown"}

    has_weekday_word = any(w in text for w in _WEEKDAY_WORDS)
    has_weekend_word = any(w in text for w in _WEEKEND_WORDS)
    # "09:00~18:00(주말 및 공휴일 제외)"처럼 "평일"/"주중"이라는 단어 없이
    # "주말...제외/미운영/미개방"으로만 평일 전용임을 나타내는 경우도 커버한다.
    weekend_excluded_phrase = has_weekend_word and any(w in text for w in _WEEKEND_EXCLUDED_WORDS)

    ranges = _find_ranges(text)

    if (has_weekday_word or weekend_excluded_phrase) and has_weekend_word and len(ranges) >= 2:
        # "주중 08:00~19:00, 주말 09:00~18:00" 같은 형태 - 실제 관측 데이터에서
        # 첫 번째 범위가 평일, 두 번째가 주말 순서로 등장해 그 순서를 따른다.
        wd_start, wd_end = ranges[0]
        we_start, we_end = ranges[1]
        return {
            "kind": "weekday_weekend",
            "start": wd_start,
            "end": wd_end,
            "weekendStart": we_start,
            "weekendEnd": we_end,
        }

    if has_weekday_word or weekend_excluded_phrase:
        if ranges:
            start, end = ranges[0]
            return {"kind": "weekday_only", "start": start, "end": end}
        return {"kind": "unknown"}

    if ranges:
        start, end = ranges[0]
        return {"kind": "daily", "start": start, "end": end}

    return {"kind": "unknown"}
