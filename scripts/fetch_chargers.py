#!/usr/bin/env python3
"""
한국환경공단 전기자동차 충전소 정보(getChargerInfo) API에서 전국 데이터를 받아
아래 조건으로 필터링한 뒤 docs/data/chargers.geojson 으로 저장한다.

필터 조건
  1) limitYn == "N"            : 이용자 제한 없음
  2) parkingFree == "Y"        : 주차료 무료
  3) chgerType in {02, 09, 10} : AC완속 / NACS / DC콤보+NACS
  4) delYn != "Y"              : 삭제(철거)된 충전기 제외

같은 statId(충전소)에 속한 충전기는 하나의 지도 마커(station)로 묶고,
각 충전기의 상태(stat)는 개별 항목으로 보존해 팝업에서 구분 표시한다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

API_URL = "http://apis.data.go.kr/B552584/EvCharger/getChargerInfo"
NUM_OF_ROWS = 9999
MAX_RETRIES = 3
RETRY_WAIT_SEC = 3

ALLOWED_CHGER_TYPES = {"02", "09", "10"}  # AC완속 / NACS / DC콤보+NACS

CHGER_TYPE_NAMES = {
    "01": "DC차데모",
    "02": "AC완속",
    "03": "DC차데모+AC3상",
    "04": "DC콤보",
    "05": "DC차데모+DC콤보",
    "06": "DC차데모+AC3상+DC콤보",
    "07": "AC3상",
    "08": "DC콤보(완속)",
    "09": "NACS",
    "10": "DC콤보+NACS",
}

STAT_NAMES = {
    "0": "알수없음",
    "1": "통신이상",
    "2": "사용가능",
    "3": "충전중",
    "4": "운영중지",
    "5": "점검중",
}


def get_service_key():
    key = os.environ.get("EV_SERVICE_KEY")
    if not key:
        print("EV_SERVICE_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_page(service_key, page_no):
    params = {
        "serviceKey": service_key,
        "pageNo": page_no,
        "numOfRows": NUM_OF_ROWS,
        "dataType": "JSON",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except (urllib.error.URLError, json.JSONDecodeError) as err:
            last_err = err
            print(f"  경고: 페이지 {page_no} 요청 실패({attempt}/{MAX_RETRIES}): {err}", file=sys.stderr)
            time.sleep(RETRY_WAIT_SEC)
    raise RuntimeError(f"페이지 {page_no} 요청이 반복적으로 실패했습니다: {last_err}")


def fetch_all(service_key):
    items = []
    page_no = 1
    total_count = None
    while True:
        data = fetch_page(service_key, page_no)
        result_code = data.get("resultCode")
        if result_code not in (None, "00"):
            raise RuntimeError(f"API 오류(resultCode={result_code}): {data.get('resultMsg')}")

        if total_count is None:
            total_count = int(data.get("totalCount", 0))
            print(f"전체 데이터: {total_count}건")

        page_items = data.get("items", {})
        page_items = page_items.get("item", []) if isinstance(page_items, dict) else []
        if isinstance(page_items, dict):
            page_items = [page_items]

        if not page_items:
            break

        items.extend(page_items)
        print(f"  페이지 {page_no}: {len(page_items)}건 (누적 {len(items)}/{total_count})")

        if len(items) >= total_count:
            break
        page_no += 1
        time.sleep(0.2)

    return items


def passes_filter(item):
    if item.get("limitYn") != "N":
        return False
    if item.get("parkingFree") != "Y":
        return False
    if item.get("chgerType") not in ALLOWED_CHGER_TYPES:
        return False
    if item.get("delYn") == "Y":
        return False
    return True


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
                "lat": lat,
                "lng": lng,
                "chargers": [],
            }

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
    items = fetch_all(service_key)
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
