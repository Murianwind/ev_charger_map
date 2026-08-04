"""한국환경공단 EvCharger API 전용 로직.

- 페이지네이션(전체 item 수집)
- 필터 조건 (완속/NACS 타입, 이용제한, 학교/아파트 제외 등)
- 시도(zcode) 요일별 그룹 — 하루에 전국을 다 스캔하는 대신 7일에 나눠 담당
- 원본 item -> station dict 변환 (GeoJSON 변환은 geojson_store의 책임)
"""
import time
import urllib.parse
from collections import OrderedDict

from http_client import fetch_json

API_BASE = "https://apis.data.go.kr/B552584/EvCharger"
QUOTA_MARKER = "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"

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
    "2": "충전대기",
    "3": "충전중",
    "4": "운영중지",
    "5": "점검중",
    "6": "예약중",
    "9": "상태미확인",
}

EXCLUDED_KIND_DETAILS = {"J001", "H001"}  # 학교, 아파트
# limitDetail 또는 useTime에 이 문구가 있으면 limitYn=N/kindDetail 분류와 무관하게 제외
# (아파트 등이 kindDetail로 정확히 분류 안 돼 있는 경우가 있어 텍스트로 한 번 더 거른다).
# "불가"/"금지"는 "사용불가"/"이용불가"/"출입금지" 등을 폭넓게 잡는다(오탐 위험 낮음).
# "거주자"/"입주민"/"외부인"은 가이드 공식 예시("거주자외")와 실제 관측 문구
# ("외부인 사용불가", "입주민만 사용가능 거주자 외출입제한")를 커버한다.
NON_OPEN_KEYWORDS = ("비개방", "불가", "금지", "외부인", "입주민", "거주자")

# 가이드 문서 공식 zcode(시도 코드) 표. 전국을 매번 한 번에 스캔하면 하루 API
# 호출 한도(1,000건)를 계속 위태롭게 넘나들게 되어, 요일별로 나눠 담당한다.
# 인구/충전기 밀집도가 큰 지역과 작은 지역을 섞어 하루 부담을 비슷하게
# 맞췄다 — 정확한 지역별 건수는 실측 후 필요하면 이 매핑만 조정하면 된다.
# 인덱스는 datetime.weekday() 기준 (월=0 ... 일=6).
DAY_ZCODE_GROUPS = [
    ["41", "44", "50"],  # 월: 경기, 충남, 제주
    ["11", "12", "36"],  # 화: 서울, 전남광주통합, 세종
    ["26", "30"],  # 수: 부산, 대전
    ["48", "43"],  # 목: 경남, 충북
    ["28", "51"],  # 금: 인천, 강원
    ["47", "52"],  # 토: 경북, 전북
    ["27", "31"],  # 일: 대구, 울산
]


def _build_url(operation, service_key, page_no, num_of_rows, extra_params):
    params = {
        # serviceKey가 이미 URL 인코딩된 형태(data.go.kr "Encoding" 키)로 저장돼
        # 있으면 urlencode()가 %를 다시 %25로 인코딩해서 키가 깨진다(이중 인코딩).
        # 먼저 unquote로 한 번 풀어두면, 원본(Decoding) 키든 인코딩된 키든
        # urlencode()에서 정확히 한 번만 인코딩되어 항상 같은 결과가 나온다.
        "serviceKey": urllib.parse.unquote(service_key),
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "dataType": "JSON",
    }
    if extra_params:
        params.update(extra_params)
    return f"{API_BASE}/{operation}?{urllib.parse.urlencode(params)}"


def _fetch_all_pages(operation, service_key, extra_params=None, num_of_rows=1000):
    """totalCount에 도달할 때까지 pageNo를 늘려가며 전체 item을 모아 반환한다."""
    items = []
    page_no = 1
    total_count = None

    while True:
        url = _build_url(operation, service_key, page_no, num_of_rows, extra_params)
        data = fetch_json(url, quota_marker=QUOTA_MARKER)

        result_code = data.get("resultCode")
        if result_code not in (None, "00"):
            raise RuntimeError(f"API 오류(resultCode={result_code}): {data.get('resultMsg')}")

        if total_count is None:
            total_count = int(data.get("totalCount", 0))

        page_items = data.get("items", {})
        page_items = page_items.get("item", []) if isinstance(page_items, dict) else []
        if isinstance(page_items, dict):
            page_items = [page_items]

        if not page_items:
            break

        items.extend(page_items)
        # 페이지가 많을 때 로그가 쓸데없이 길어지지 않도록 5페이지마다만 남긴다.
        if page_no == 1 or page_no % 5 == 0:
            print(f"[{operation}]   페이지 {page_no}: 누적 {len(items)}/{total_count}")

        if len(items) >= total_count:
            break
        page_no += 1
        time.sleep(0.2)

    print(f"[{operation}] extra_params={extra_params} 총 {len(items)}건 수집")
    return items


def passes_filter(item):
    if item.get("delYn") == "Y":
        return False

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


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_stations(items):
    """필터를 통과한 item들을 statId 기준으로 묶어 station dict 리스트로 만든다.
    (GeoJSON feature 변환은 geojson_store의 책임이라 여기선 순수 데이터만 만든다.)
    """
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
                # 지역별 부분 교체(geojson_store.replace_regions)를 위해 보존한다.
                "zcode": item.get("zcode", ""),
                "isTesla": False,
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

    return list(stations.values())


def fetch_region(service_key, zcodes):
    """주어진 zcode들의 전체 정보를 받아 필터링된 station dict 리스트로 반환한다."""
    all_items = []
    for zcode in zcodes:
        all_items.extend(_fetch_all_pages("getChargerInfo", service_key, {"zcode": zcode}))
    return build_stations(all_items)


def fetch_status_delta(service_key, period_min):
    """getChargerStatus 델타 피드를 가공 없이 그대로 반환한다."""
    return _fetch_all_pages("getChargerStatus", service_key, {"period": period_min})
