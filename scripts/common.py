"""fetch_chargers.py / fetch_status.py 공용 상수 및 API 호출 헬퍼."""
import json
import subprocess
import time
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

API_BASE = "https://apis.data.go.kr/B552584/EvCharger"
MAX_RETRIES = 2
RETRY_WAIT_SEC = 3
CURL_TIMEOUT_SEC = 60

# JSON 경로에서 계속 403이 나서 XML로 테스트해보기 위한 스위치.
# JSON으로 되돌리려면 "JSON"으로 바꾸면 된다 (나머지 코드는 그대로 동작).
DATA_TYPE = "JSON"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

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


def _xml_to_result(body):
    """XML 응답을 JSON 파싱 결과와 같은 모양의 dict로 변환한다."""
    root = ET.fromstring(body)
    header = root.find("header")
    result_code = header.findtext("resultCode") if header is not None else None
    result_msg = header.findtext("resultMsg") if header is not None else None

    body_el = root.find("body")
    total_count = 0
    items = []
    if body_el is not None:
        total_count = int(body_el.findtext("totalCount") or 0)
        items_el = body_el.find("items")
        if items_el is not None:
            for item_el in items_el.findall("item"):
                items.append({child.tag: (child.text or "") for child in item_el})

    return {
        "resultCode": result_code,
        "resultMsg": result_msg,
        "totalCount": total_count,
        "items": {"item": items},
    }


def call_api(operation, params, page_no):
    query = {**params, "pageNo": page_no}
    # serviceKey가 이미 URL 인코딩된 형태(data.go.kr "Encoding" 키)로 저장돼 있으면
    # urlencode()가 %를 다시 %25로 인코딩해서 키가 깨진다(이중 인코딩).
    # 먼저 unquote로 한 번 풀어두면, 원본(Decoding) 키든 인코딩된 키든
    # urlencode()에서 정확히 한 번만 인코딩되어 항상 같은 결과가 나온다.
    if "serviceKey" in query:
        query["serviceKey"] = urllib.parse.unquote(query["serviceKey"])
    url = f"{API_BASE}/{operation}?{urllib.parse.urlencode(query)}"

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Python(urllib/OpenSSL)이 이 서버의 TLS 재협상(renegotiation) 요구를
            # 제대로 처리 못 하고 무한 대기하는 것으로 보여, curl을 서브프로세스로
            # 직접 호출한다 (Windows curl에서는 항상 정상 동작했음).
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-A", USER_AGENT,
                    "--max-time", str(CURL_TIMEOUT_SEC),
                    url,
                ],
                capture_output=True,
                timeout=CURL_TIMEOUT_SEC + 5,
                check=True,
            )
            body = result.stdout.decode("utf-8")
            if DATA_TYPE == "JSON":
                return json.loads(body)
            return _xml_to_result(body)
        except (subprocess.SubprocessError, json.JSONDecodeError, ET.ParseError) as err:
            last_err = err
            print(f"  경고: {operation} 페이지 {page_no} 요청 실패({attempt}/{MAX_RETRIES}): {err}")
            time.sleep(RETRY_WAIT_SEC)
    raise RuntimeError(f"{operation} 페이지 {page_no} 요청이 반복적으로 실패했습니다: {last_err}")


def fetch_all(operation, params, num_of_rows=1000):
    """totalCount에 도달할 때까지 pageNo를 늘려가며 전체 item을 모아 반환한다."""
    items = []
    page_no = 1
    total_count = None
    base_params = {**params, "numOfRows": num_of_rows, "dataType": DATA_TYPE}

    while True:
        data = call_api(operation, base_params, page_no)
        result_code = data.get("resultCode")
        if result_code not in (None, "00"):
            raise RuntimeError(f"API 오류(resultCode={result_code}): {data.get('resultMsg')}")

        if total_count is None:
            total_count = int(data.get("totalCount", 0))
            print(f"[{operation}] 전체 데이터: {total_count}건")

        page_items = data.get("items", {})
        page_items = page_items.get("item", []) if isinstance(page_items, dict) else []
        if isinstance(page_items, dict):
            page_items = [page_items]

        if not page_items:
            break

        items.extend(page_items)
        print(f"[{operation}]   페이지 {page_no}: {len(page_items)}건 (누적 {len(items)}/{total_count})")

        if len(items) >= total_count:
            break
        page_no += 1
        time.sleep(0.2)

    return items


SUPERCHARGE_INFO_URL = "https://supercharge.info/service/supercharge/allSites"

# supercharge.info의 stalls 필드 키 -> 표시 라벨
STALL_VERSION_LABELS = {
    "v2": "V2",
    "v3": "V3",
    "v4": "V4",
    "urban": "Urban",
    "other": "기타",
}


def fetch_tesla_superchargers():
    """supercharge.info(테슬라 슈퍼차저 커뮤니티 오픈 데이터베이스)에서
    한국 소재의 '운영중(OPEN)' 슈퍼차저만 받아와, 기존 chargers.geojson과
    호환되는 station dict 포맷으로 변환해 반환한다.

    한국환경공단 API에는 테슬라(busiId=TE) 데이터가 실질적으로 없어서
    (실측 결과 전국 0건) 별도 소스로 보강한다.

    이 API는 실시간 사용 가능 여부를 제공하지 않아서, 개별 커넥터 상태를
    지어내지 않고 "충전기 N개 (V3 N개) 최대 250kW" 형태의 요약 텍스트
    (teslaSummary)만 만들어 저장한다.
    """
    try:
        result = subprocess.run(
            ["curl", "-s", "-A", USER_AGENT, "--max-time", str(CURL_TIMEOUT_SEC), SUPERCHARGE_INFO_URL],
            capture_output=True,
            timeout=CURL_TIMEOUT_SEC + 5,
            check=True,
        )
        sites = json.loads(result.stdout.decode("utf-8"))
    except (subprocess.SubprocessError, json.JSONDecodeError) as err:
        print(f"경고: 테슬라 슈퍼차저(supercharge.info) 조회 실패, 건너뜀: {err}")
        return []

    stations = []
    for site in sites:
        addr = site.get("address") or {}
        country = addr.get("country") or ""
        if "korea" not in country.lower():
            continue
        if site.get("status") != "OPEN":
            continue

        gps = site.get("gps") or {}
        lat, lng = gps.get("latitude"), gps.get("longitude")
        if lat is None or lng is None:
            continue

        stalls = site.get("stalls") or {}
        total_stalls = site.get("stallCount") or sum(
            v for k, v in stalls.items() if k in STALL_VERSION_LABELS
        )
        version_parts = [
            f"{STALL_VERSION_LABELS[k]} {stalls[k]}개"
            for k in STALL_VERSION_LABELS
            if stalls.get(k)
        ]
        power_kw = site.get("powerKilowatt")

        summary = f"충전기 {total_stalls}개"
        if version_parts:
            summary += f" ({', '.join(version_parts)})"
        if power_kw:
            summary += f" 최대 {power_kw}kW"

        stations.append(
            {
                "statId": f"TESLA-{site.get('id')}",
                "statNm": site.get("name") or "테슬라 수퍼차저",
                "addr": " ".join(filter(None, [addr.get("state"), addr.get("city")])),
                "addrDetail": addr.get("street") or "",
                "location": site.get("facilityName") or "",
                "useTime": site.get("hours") or "24시간 이용가능",
                "busiNm": "테슬라",
                "busiCall": "",
                "parkingFree": "Y",
                "limitYn": "N",
                "limitDetail": "",
                "floorType": "",
                "floorNum": "",
                "isTesla": True,
                "teslaSummary": summary,
                "lat": lat,
                "lng": lng,
                "chargers": [],
            }
        )

    print(f"[supercharge.info] 한국 내 운영중 슈퍼차저 {len(stations)}개소")
    return stations


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
