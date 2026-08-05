"""한국환경공단 EvCharger API 전용 로직.

- 페이지네이션(전체 item 수집)
- 필터 조건 (완속/NACS 타입, 이용제한, 학교/아파트 제외 등)
- 시도(zcode) 요일별 그룹 — 하루에 전국을 다 스캔하는 대신 7일에 나눠 담당
- 원본 item -> station dict 변환 (GeoJSON 변환은 geojson_store의 책임)
- 일일 호출 한도 초과 시 다음날 자정(KST)까지 자동으로 재시도를 쉬는 쿨다운
"""
import os
import re
import time
import urllib.parse
from collections import OrderedDict
from datetime import datetime, timedelta

from http_client import QuotaExceededError, fetch_json
from kakao_geocoder import verify_and_correct
from kst_time import now_kst

API_BASE = "https://apis.data.go.kr/B552584/EvCharger"
QUOTA_MARKER = "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"

# 한도초과가 감지되면, 자정(KST)까지 재시도를 쉬겠다는 표시를 여기 남긴다.
# self-hosted 러너 컨테이너는 잡 사이에도 계속 떠있는 하나의 컨테이너라
# /tmp가 실행 간에 유지된다(GitHub 호스팅 러너처럼 매번 새 VM이 아님).
QUOTA_COOLDOWN_FILE = "/tmp/.ev_quota_cooldown"


def _in_quota_cooldown():
    if not os.path.exists(QUOTA_COOLDOWN_FILE):
        return False
    try:
        with open(QUOTA_COOLDOWN_FILE) as f:
            until = datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return False
    return now_kst() < until


def _start_quota_cooldown():
    """다음날 자정(KST)까지 쿨다운을 건다."""
    tomorrow_midnight = (now_kst() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with open(QUOTA_COOLDOWN_FILE, "w") as f:
        f.write(tomorrow_midnight.isoformat())
    return tomorrow_midnight

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
# - "불가"/"금지": "사용불가"/"이용불가"/"출입금지" 등을 폭넓게 잡는다(오탐 위험 낮음).
# - "거주자"/"입주민"/"외부인": 가이드 공식 예시("거주자외")와 실제 관측 문구
#   ("외부인 사용불가", "입주민만 사용가능 거주자 외출입제한")를 커버한다.
# - "제한될 수": "시설 상황에 따라 이용이 제한될 수 있음"처럼 조건부/불확실한
#   제한 문구를 커버한다 (실제로 이용 불가했던 사례에서 발견).
NON_OPEN_KEYWORDS = ("비개방", "불가", "금지", "외부인", "입주민", "거주자", "제한될 수")

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

# 유효한 지역 코드 16개를 평평한 집합으로도 노출한다(geojson_store.prune_orphaned에서
# "이 zcode 중 어디에도 없으면 정상 데이터가 아니다"를 판단하는 데 쓴다).
ALL_ZCODES = {z for group in DAY_ZCODE_GROUPS for z in group}

# 가이드 문서 기준 numOfRows 최댓값(최소 10, 최대 9999). 한 페이지에 최대한
# 많이 받아와야 pageNo 호출 횟수(=API 호출 횟수)가 줄어든다. 예전엔 1000을
# 썼는데, 부산(3만여 건) 기준 33페이지 -> 4페이지로 거의 8배 줄었다.
MAX_NUM_OF_ROWS = 9999


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


def _fetch_all_pages(operation, service_key, extra_params=None, num_of_rows=MAX_NUM_OF_ROWS):
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


# 원본 addr에 "주소+시설명"이 붙어서 오는 경우가 있다
# (예: "대전광역시 유성구 전민동 346-3전민동 제2공영주차장 -",
#      "대전광역시 유성구 북유성대로 172죽동 공영주차장 2~3층",
#      "대전광역시 유성구 덕명동 595학하지구 제5공영주차장",
#      "대전광역시 유성구 엑스포로 55 (도룡동, 기초과학연구원 본원)").
# 먼저 끝에 괄호로 묶인 부가설명이 있으면 떼어내 시설명 후보로 챙겨두고,
# 남은 주소에서 주소가 끝나는 지점을 우선순위대로 찾는다:
#   1. 지번(숫자-숫자, 예: 346-3) — 하이픈이 있어서 "제2공영주차장" 같은
#      시설명 속 숫자와 헷갈리지 않는다.
#   2. 도로명(로/길 + 숫자, 예: "북유성대로 172") — 도로명주소는 하이픈이
#      없는 경우가 많아서 별도로 잡는다.
#   3. (1·2 둘 다 없을 때 최후 수단) "제N"(서수) 형태가 아니면서 숫자
#      뒤에 (공백이 있든 없든) 한글이 나오는 지점 — 하이픈도 "로/길"도
#      없는 순수 지번(예: "덕명동 595", "봉산동299 공영주차장")을 잡기
#      위함. 이건 오탐 위험이 있어서 1·2가 하나도 안 잡혔을 때만 쓰고,
#      제일 먼저 나오는 지점만 쓴다(뒤쪽 시설명 안에도 이 패턴에 걸리는
#      숫자가 또 있을 수 있어서).
_LOT_NUMBER_PATTERN = re.compile(r"\d+-\d+")
_ROAD_NUMBER_PATTERN = re.compile(r"(?:로|길)\s*\d+(?:-\d+)?")
_BARE_NUMBER_GLUED_PATTERN = re.compile(r"(?<!제)\d+(?=\s*[가-힣])")
_TRAILING_PAREN_PATTERN = re.compile(r"\s*\(([^()]*)\)\s*$")


def split_addr_and_location(addr):
    """(정리된 주소, 뒤에 붙어있던 시설명) 튜플을 반환한다.
    분리할 게 없으면 시설명은 빈 문자열이다.
    """
    paren_text = ""
    paren_match = _TRAILING_PAREN_PATTERN.search(addr)
    if paren_match:
        paren_text = paren_match.group(1).strip()
        addr = addr[: paren_match.start()].strip()

    strong_matches = list(_LOT_NUMBER_PATTERN.finditer(addr)) + list(_ROAD_NUMBER_PATTERN.finditer(addr))
    if strong_matches:
        split_at = max(m.end() for m in strong_matches)
    else:
        weak_matches = list(_BARE_NUMBER_GLUED_PATTERN.finditer(addr))
        if not weak_matches:
            return addr.strip(" -"), paren_text
        split_at = weak_matches[0].end()

    address_part = addr[:split_at].strip()
    rest = addr[split_at:].strip(" -").strip()
    combined_rest = " ".join(p for p in (rest, paren_text) if p)
    return address_part, combined_rest


# addr 텍스트에 이 지역명이 있으면, 좌표가 대략 이 사각 범위(lat_min, lat_max,
# lng_min, lng_max) 안에 있어야 한다. 정확한 행정경계가 아니라 넉넉한 사각형
# 근사치라, 경계 지역에서는 드물게 오탐/누락이 있을 수 있다 — 그래도 "대전
# 주소인데 좌표는 이천"처럼 완전히 딴 지역으로 튄 경우는 확실히 잡아낸다.
PROVINCE_BOUNDS = {
    "서울": (37.42, 37.70, 126.76, 127.18),
    "인천": (37.20, 37.75, 126.05, 126.80),
    "경기": (36.90, 38.30, 126.35, 127.85),
    "강원": (37.00, 38.65, 127.55, 129.40),
    "충청북도": (36.00, 37.20, 127.30, 128.30),
    "충북": (36.00, 37.20, 127.30, 128.30),
    "충청남도": (35.90, 37.05, 126.10, 127.55),
    "충남": (35.90, 37.05, 126.10, 127.55),
    "대전": (36.20, 36.50, 127.25, 127.55),
    "세종": (36.42, 36.72, 127.10, 127.40),
    "전라북도": (35.55, 36.15, 126.40, 127.75),
    "전북": (35.55, 36.15, 126.40, 127.75),
    "전라남도": (33.90, 35.55, 125.90, 127.85),
    "전남": (33.90, 35.55, 125.90, 127.85),
    "광주": (35.00, 35.30, 126.65, 127.00),
    "경상북도": (35.65, 37.15, 128.15, 129.65),
    "경북": (35.65, 37.15, 128.15, 129.65),
    "대구": (35.65, 36.05, 128.35, 128.75),
    "경상남도": (34.75, 35.85, 127.50, 129.30),
    "경남": (34.75, 35.85, 127.50, 129.30),
    "부산": (34.85, 35.40, 128.75, 129.35),
    "울산": (35.35, 35.75, 129.10, 129.55),
    "제주": (33.10, 33.60, 126.05, 126.98),
}


def coordinates_plausible(addr, lat, lng):
    """addr가 말하는 지역과 실제 (lat, lng)가 대략 맞는지 확인한다.
    addr에서 알아볼 수 있는 지역명이 없으면 판단하지 않고 통과시킨다
    (틀렸다고 확신할 근거가 없을 때 잘못 걸러내지 않기 위함).
    """
    for province, (lat_min, lat_max, lng_min, lng_max) in PROVINCE_BOUNDS.items():
        if province in addr:
            return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max
    return True


def build_stations(items):
    """필터를 통과한 item들을 statId 기준으로 묶어 station dict 리스트로 만든다.
    (GeoJSON feature 변환은 geojson_store의 책임이라 여기선 순수 데이터만 만든다.)
    """
    stations = OrderedDict()
    skipped_stat_ids = set()  # 좌표 문제로 제외 결정된 충전소(같은 충전소의
                               # 다른 커넥터 item이 뒤에 또 나와도 다시 검사 안 함)
    skipped_bad_coord = 0
    skipped_coord_mismatch = 0
    corrected_by_kakao = 0

    for item in items:
        if not passes_filter(item):
            continue

        stat_id = item.get("statId")
        if stat_id in skipped_stat_ids:
            continue

        lat = to_float(item.get("lat"))
        lng = to_float(item.get("lng"))
        if not stat_id or lat is None or lng is None:
            skipped_bad_coord += 1
            continue

        if stat_id not in stations:
            # 충전소 하나에 커넥터가 여러 개면 같은 statId로 여러 번 나오는데,
            # 주소 정리/지오코딩은 처음 등장할 때 딱 한 번만 한다 (안 그러면
            # 커넥터 개수만큼 같은 주소를 카카오에 중복 조회하게 된다).
            addr, extracted_location = split_addr_and_location(item.get("addr", ""))

            # 카카오 지오코딩으로 좌표를 검증/보정한다 (KAKAO_REST_API_KEY가
            # 있을 때만 실제로 호출됨). 뒤섞인 원본 대신 정리된 주소를 보내야
            # 인식률이 올라간다. 지오코딩이 실패하면(키 미설정, 주소 인식 불가
            # 등) 기존의 대략적인 도(道) 사각형 검증으로 최소한의 안전망만
            # 적용한다.
            lat, lng, geo_status = verify_and_correct(addr, lat, lng)
            if geo_status == "corrected":
                corrected_by_kakao += 1
                print(f"  안내: 좌표 보정(카카오) — {item.get('statNm', '')} ({addr})")
            elif geo_status == "unavailable" and not coordinates_plausible(addr, lat, lng):
                # 원본 API 데이터 자체의 좌표 오류로 보인다 (예: 주소는 대전인데
                # 좌표는 이천 근방). 필터 텍스트로는 못 잡는 문제라 여기서 걸러낸다.
                skipped_coord_mismatch += 1
                print(f"  경고: 좌표 불일치로 제외 — {item.get('statNm', '')} ({addr})")
                skipped_stat_ids.add(stat_id)
                continue

            # addr에서 분리해낸 시설명(있으면 먼저)과 API 자체 location 값을
            # 둘 다 있으면 이어붙인다 (예: 괄호 부가설명 "기초과학연구원 본원"
            # + API가 준 "지상1층 주차장" -> "기초과학연구원 본원 지상1층 주차장").
            location = " ".join(
                p for p in (extracted_location, item.get("location", "").strip()) if p
            )

            stations[stat_id] = {
                "statId": stat_id,
                "statNm": item.get("statNm", ""),
                "addr": addr,
                "addrDetail": item.get("addrDetail", ""),
                "location": location,
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
    if skipped_coord_mismatch:
        print(f"주소-좌표 불일치로 제외: {skipped_coord_mismatch}건")
    if corrected_by_kakao:
        print(f"카카오 지오코딩으로 좌표 보정: {corrected_by_kakao}건")

    return list(stations.values())


def fetch_region(service_key, zcodes):
    """주어진 zcode들의 전체 정보를 받아 필터링된 station dict 리스트로 반환한다.

    한도초과 쿨다운 중이거나, 이번 호출에서 한도초과가 감지되면 None을
    반환한다 (호출부가 "이번엔 건너뜀"으로 처리하도록).
    """
    if _in_quota_cooldown():
        print("[gov_charger_api] 오늘 API 한도 초과로 쿨다운 중 — 지역 갱신 건너뜀")
        return None
    try:
        all_items = []
        for zcode in zcodes:
            all_items.extend(_fetch_all_pages("getChargerInfo", service_key, {"zcode": zcode}))
        return build_stations(all_items)
    except QuotaExceededError:
        until = _start_quota_cooldown()
        print(f"[gov_charger_api] API 한도 초과 감지 — {until.isoformat()}까지 쿨다운 시작")
        return None


def fetch_status_delta(service_key, period_min):
    """getChargerStatus 델타 피드를 가공 없이 그대로 반환한다.

    period_min은 API 문서 기준 1~10만 유효하다(기본값 5). 이보다 크게 주면
    그 사이 변경분을 놓칠 수 있어(문서에 명시된 범위를 벗어남), 호출 주기와
    period를 항상 10분/10 이하로 맞춰야 한다.

    한도초과 쿨다운 중이거나, 이번 호출에서 한도초과가 감지되면 None을 반환한다.
    """
    if _in_quota_cooldown():
        print("[gov_charger_api] 오늘 API 한도 초과로 쿨다운 중 — 상태 갱신 건너뜀")
        return None
    try:
        return _fetch_all_pages("getChargerStatus", service_key, {"period": period_min})
    except QuotaExceededError:
        until = _start_quota_cooldown()
        print(f"[gov_charger_api] API 한도 초과 감지 — {until.isoformat()}까지 쿨다운 시작")
        return None
