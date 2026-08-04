#!/usr/bin/env python3
"""
일일 지역 갱신 진입점.

한국환경공단 getChargerInfo API로 전국을 한 번에 스캔하면 하루 API 호출
한도(1,000건)를 계속 위태롭게 넘나들게 된다. 그래서 16개 시도를 7일에
나눠 담당한다(gov_charger_api.DAY_ZCODE_GROUPS). 매일 그날 담당 지역만
새로 받아 기존 데이터에서 그 지역만 교체하고, 나머지 지역은 지난 회차
데이터를 그대로 유지한다 — 일주일이면 전국이 한 바퀴 갱신된다.

처음 배포하거나 데이터를 통째로 새로 채워넣고 싶을 때는 환경변수
FULL_SEED=1로 실행한다 (모든 지역을 한 번에 순회 — 호출량이 크므로 수동
1회용, 평소 자동 실행에는 절대 안 쓴다).

테슬라 슈퍼차저는 별도 무료 API(supercharge.info)라 정부 API 한도와
무관하게 매일 갱신한다.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import geojson_store
from geojson_store import load_geojson, replace_regions, replace_tesla, save_geojson
from gov_charger_api import DAY_ZCODE_GROUPS, fetch_region
from tesla_source import fetch_tesla_superchargers

KST = timezone(timedelta(hours=9))


def get_service_key():
    key = os.environ.get("EV_SERVICE_KEY")
    if not key:
        print("EV_SERVICE_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


def todays_zcodes():
    if os.environ.get("FULL_SEED") == "1":
        print("FULL_SEED=1: 전체 지역을 한 번에 갱신합니다 (호출량 큼)")
        return [z for group in DAY_ZCODE_GROUPS for z in group]
    weekday = datetime.now(KST).weekday()  # 월=0 ... 일=6
    return DAY_ZCODE_GROUPS[weekday]


def main():
    service_key = get_service_key()
    zcodes = todays_zcodes()
    print(f"오늘 담당 지역(zcode): {zcodes}")

    stations = fetch_region(service_key, zcodes)

    geojson = load_geojson()
    geojson = replace_regions(geojson, zcodes, stations)

    tesla_stations = fetch_tesla_superchargers()
    geojson = replace_tesla(geojson, tesla_stations)

    save_geojson(geojson)

    total = len(geojson["features"])
    print(
        f"완료: 지역 {zcodes} {len(stations)}개소 갱신, "
        f"테슬라 {len(tesla_stations)}개소, 전체 {total}개소 저장 → {geojson_store.GEOJSON_PATH}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # 최상위 예외 캐치: 트레이스백 대신 명확한 메시지로 종료
        print(f"오류: 지역 갱신 실패 — {err}", file=sys.stderr)
        sys.exit(1)
