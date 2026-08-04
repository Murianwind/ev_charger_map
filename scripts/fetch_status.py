#!/usr/bin/env python3
"""
getChargerStatus는 'period'(분) 안에 상태가 바뀐 충전기만 돌려주는 델타 피드다.
그래서 이 스크립트는 전국 데이터를 통째로 다시 받지 않고, 최근 변경분만 받아
기존 docs/data/chargers.geojson에 병합한다 (호출 수를 적게 유지하기 위함).

호출 주기와 겹치게 period를 잡아서(예: 1시간 간격이면 period=60), 실행이
몇 분 밀리거나 한 번 실패해도 변경 이력이 빠지지 않도록 한다.

이미 chargers.geojson에 없는 statId/chgerId(= fetch_chargers.py의 필터에
안 걸린 충전기, 또는 아직 이번 주 로테이션 차례가 안 돌아온 지역)는
그대로 무시한다.
"""
import os
import sys

from geojson_store import load_geojson, save_geojson
from gov_charger_api import STAT_NAMES, fetch_status_delta

STATUS_PERIOD_MIN = int(os.environ.get("EV_STATUS_PERIOD_MIN", "60"))


def get_service_key():
    key = os.environ.get("EV_SERVICE_KEY")
    if not key:
        print("EV_SERVICE_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


def build_lookup(geojson):
    """(statId, chgerId) -> charger dict 참조를 만든다 (in-place 수정용)."""
    lookup = {}
    for feature in geojson["features"]:
        stat_id = feature["properties"]["statId"]
        for charger in feature["properties"]["chargers"]:
            lookup[(stat_id, charger["chgerId"])] = charger
    return lookup


def main():
    service_key = get_service_key()
    geojson = load_geojson()
    if not geojson["features"]:
        print("chargers.geojson이 비어 있습니다. 먼저 fetch_chargers.py를 실행하세요.", file=sys.stderr)
        sys.exit(1)

    lookup = build_lookup(geojson)
    delta_items = fetch_status_delta(service_key, STATUS_PERIOD_MIN)

    updated = 0
    ignored = 0
    for item in delta_items:
        key = (item.get("statId"), item.get("chgerId"))
        charger = lookup.get(key)
        if charger is None:
            # 우리 필터 밖이거나, 아직 이번 주 로테이션 차례가 안 돌아온 지역
            ignored += 1
            continue
        charger["stat"] = item.get("stat", charger.get("stat"))
        charger["statName"] = STAT_NAMES.get(item.get("stat"), item.get("stat"))
        charger["statUpdDt"] = item.get("statUpdDt", charger.get("statUpdDt"))
        updated += 1

    print(f"상태 변경 반영: {updated}건 / 무시: {ignored}건")

    if updated:
        save_geojson(geojson)
        print("저장 완료")
    else:
        print("변경 사항 없음, 파일 저장 생략")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # 최상위 예외 캐치: 트레이스백 대신 명확한 메시지로 종료
        print(f"오류: 상태 갱신 실패 — {err}", file=sys.stderr)
        sys.exit(1)
