#!/usr/bin/env python3
"""
한국환경공단 getChargerInfo API에서 전국 충전소 '전체 정보'(위치/타입/이용조건 등)를
받아 필터링한 뒤 docs/data/chargers.geojson 으로 저장한다.

이 스크립트는 하루 1회 실행을 기준으로 설계했다 (전국 데이터라 numOfRows=9999
기준으로도 페이지 수십 회가 필요해, 자주 돌리면 API 일일 호출 한도를 금방 씀).
충전기 '상태(stat)'만 자주 갱신하고 싶다면 fetch_status.py를 더 짧은 주기로 돌린다.

필터 조건
  1) limitYn == "N"            : 이용자 제한 없음
  2) parkingFree == "Y"        : 주차료 무료
  3) chgerType in {02, 09, 10} : AC완속 / NACS / DC콤보+NACS
  4) delYn != "Y"              : 삭제(철거)된 충전기 제외
  5) kindDetail이 학교/아파트가 아닐 것
  6) limitDetail/useTime에 "비개방","외부인","입주민","거주자" 등의 문구가 없을 것
     (아파트 등이 kindDetail로 정확히 분류 안 돼 있는 경우가 있어 텍스트로 한 번 더 거른다)

  예외: busiId == "TE"(테슬라)인 충전기는 위 조건과 무관하게 전부 포함한다
  (단, 삭제된 충전기는 테슬라여도 제외).
"""
import json
import os
import sys
from collections import OrderedDict

from common import ALLOWED_CHGER_TYPES, CHGER_TYPE_NAMES, STAT_NAMES, fetch_all, to_float


TESLA_BUSI_ID = "TE"


def get_service_key():
    key = os.environ.get("EV_SERVICE_KEY")
    if not key:
        print("EV_SERVICE_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


EXCLUDED_KIND_DETAILS = {"J001", "H001"}  # 학교, 아파트
# limitDetail 또는 useTime에 이 문구가 있으면 limitYn=N/kindDetail 분류와 무관하게 제외
# (아파트 등이 kindDetail로 정확히 분류 안 돼 있는 경우가 있어 텍스트로 한 번 더 거른다)
NON_OPEN_KEYWORDS = ("비개방", "외부인", "입주민", "거주자", "금지", "불가")


def passes_filter(item):
    if item.get("delYn") == "Y":
        return False

    if item.get("busiId") == TESLA_BUSI_ID:
        # 테슬라 슈퍼차저는 다른 조건과 무관하게 무조건 전부 포함
        return True

    if item.get("kindDetail") in EXCLUDED_KIND_DETAILS:
        return False

    text_fields = f"{item.get('limitDetail') or ''} {item.get('useTime') or ''}"
    if any(keyword in text_fields for keyword in NON_OPEN_KEYWORDS):
        return False

    if item.get("limitYn") != "N":
        return False
    if item.get("parkingFree") != "Y":
        return False
    if item.get("chgerType") not in ALLOWED_CHGER_TYPES:
        return False
    return True


def build_geojson(items):
    stations = OrderedDict()
    skipped_bad_coord = 0

    for item in items:
        if not passes_filter(item):
            continue

        stat_id = item.get("statId")
        lat = to_float(item.get("lat"))
        lng = to_float(item.get("lng"))
        if not stat_id or lat is None or lng is None:
            skipped_bad_coord += 1
            continue

        if stat_id not in stations:
            stations[stat_id] = {
                "statId": stat_id,
                "statNm": item.get("statNm", ""),
                "addr": item.get("addr", ""),
                "addrDetail": item.get("addrDetail", ""),
                "location": item.get("location", ""),
                "useTime": item.get("useTime", ""),
                "busiNm": item.get("busiNm", ""),
                "busiCall": item.get("busiCall", ""),
                "parkingFree": item.get("parkingFree", ""),
                "limitYn": item.get("limitYn", ""),
                # limitYn=N이어도 limitDetail에 내용이 남아있는 경우가 있어
                # 그대로 보존한다 (추후 필터 조건 보강용 참고 정보).
                "limitDetail": item.get("limitDetail", ""),
                "floorType": item.get("floorType", ""),
                "floorNum": item.get("floorNum", ""),
                "isTesla": False,
                "lat": lat,
                "lng": lng,
                "chargers": [],
            }

        if item.get("busiId") == TESLA_BUSI_ID:
            stations[stat_id]["isTesla"] = True

        stations[stat_id]["chargers"].append(
            {
                "chgerId": item.get("chgerId", ""),
                "chgerType": item.get("chgerType", ""),
                "chgerTypeName": CHGER_TYPE_NAMES.get(item.get("chgerType"), item.get("chgerType")),
                "stat": item.get("stat", ""),
                "statName": STAT_NAMES.get(item.get("stat"), item.get("stat")),
                "output": item.get("output", ""),
                "method": item.get("method", ""),
                "statUpdDt": item.get("statUpdDt", ""),
            }
        )

    if skipped_bad_coord:
        print(f"좌표 누락/오류로 제외: {skipped_bad_coord}건")

    features = []
    for s in stations.values():
        lat, lng = s["lat"], s["lng"]
        props = {k: v for k, v in s.items() if k not in ("lat", "lng")}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def main():
    service_key = get_service_key()
    items = fetch_all("getChargerInfo", {"serviceKey": service_key})
    geojson = build_geojson(items)

    out_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "docs", "data", "chargers.geojson")
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"완료: 충전소 {len(geojson['features'])}개소 저장 → {out_path}")


if __name__ == "__main__":
    main()