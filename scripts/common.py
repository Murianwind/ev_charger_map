"""fetch_chargers.py / fetch_status.py 공용 상수 및 API 호출 헬퍼."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://apis.data.go.kr/B552584/EvCharger"
MAX_RETRIES = 1
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
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except (OSError, json.JSONDecodeError) as err:
            last_err = err
            print(f"  경고: {operation} 페이지 {page_no} 요청 실패({attempt}/{MAX_RETRIES}): {err}")
            time.sleep(RETRY_WAIT_SEC)
    raise RuntimeError(f"{operation} 페이지 {page_no} 요청이 반복적으로 실패했습니다: {last_err}")


def fetch_all(operation, params, num_of_rows=9999):
    """totalCount에 도달할 때까지 pageNo를 늘려가며 전체 item을 모아 반환한다."""
    items = []
    page_no = 1
    total_count = None
    base_params = {**params, "numOfRows": num_of_rows, "dataType": "JSON"}

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


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
