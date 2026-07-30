#!/usr/bin/env python3
"""
getChargerStatus는 'period'(분) 안에 상태가 바뀐 충전기만 돌려주는 델타 피드다.
그래서 이 스크립트는 전국 데이터를 통째로 다시 받지 않고, 최근 변경분만 받아
기존 docs/data/chargers.geojson에 병합한다 (호출 수를 적게 유지하기 위함).

10분 간격으로 돌릴 계획이면 period=10으로 겹치게 잡아서, 실행이 몇 분 밀리거나
한 번 실패해도 변경 이력이 빠지지 않도록 한다.

이미 chargers.geojson에 없는 statId/chgerId(= fetch_chargers.py의 필터에
안 걸린 충전기)는 그대로 무시한다.
"""
import json
import os
import sys

from common import STAT_NAMES, fetch_all

GEOJSON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "data", "chargers.geojson")
)

STATUS_PERIOD_MIN = int(os.environ.get("EV_STATUS_PERIOD_MIN", "10"))


def get_service_key():
    key = os.environ.get("EV_SERVICE_KEY")
    if not key:
        print("EV_SERVICE_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


def load_geojson():
    if not os.path.exists(GEOJSON_PATH):
        print(f"{GEOJSON_PATH} 가 없습니다. 먼저 fetch_chargers.py를 실행하세요.", file=sys.stderr)
        sys.exit(1)
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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
    lookup = build_lookup(geojson)

    delta_items = fetch_all(
        "getChargerStatus",
        {"serviceKey": service_key, "period": STATUS_PERIOD_MIN},
    )

    updated = 0
    ignored = 0
    for item in delta_items:
        key = (item.get("statId"), item.get("chgerId"))
        charger = lookup.get(key)
        if charger is None:
            # 우리 필터(이용제한/무료주차/완속타입) 밖에 있는 충전기라 지도에 없음
            ignored += 1
            continue
        charger["stat"] = item.get("stat", charger.get("stat"))
        charger["statName"] = STAT_NAMES.get(item.get("stat"), item.get("stat"))
        charger["statUpdDt"] = item.get("statUpdDt", charger.get("statUpdDt"))
        updated += 1

    print(f"상태 변경 반영: {updated}건 / 필터 밖이라 무시: {ignored}건")

    if updated:
        with open(GEOJSON_PATH, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        print(f"저장 완료 → {GEOJSON_PATH}")
    else:
        print("변경 사항 없음, 파일 저장 생략")


if __name__ == "__main__":
    main()
