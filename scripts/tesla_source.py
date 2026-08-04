"""supercharge.info(테슬라 슈퍼차저 커뮤니티 오픈 데이터베이스) 전용 로직."""
from http_client import fetch_json

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
    """한국 소재의 '운영중(OPEN)' 슈퍼차저만 받아와 station dict 리스트로 반환한다.

    한국환경공단 API에는 테슬라(busiId=TE) 데이터가 실질적으로 없어서
    (실측 결과 전국 0건) 이 별도 소스로 보강한다. 정부 API 일일 한도와
    무관한 외부 무료 API라 매일 갱신해도 부담이 없다.

    이 API는 실시간 사용 가능 여부를 제공하지 않아서, 개별 커넥터 상태를
    지어내지 않고 "충전기 N개 (V3 N개) 최대 250kW" 형태의 요약 텍스트
    (teslaSummary)만 만들어 저장한다.
    """
    try:
        sites = fetch_json(SUPERCHARGE_INFO_URL)
    except Exception as err:  # noqa: BLE001 - 외부 API 실패는 전체 실행을 막지 않고 건너뛴다
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

        raw_name = site.get("name") or "테슬라 수퍼차저"
        station_name = raw_name.replace(", South Korea", "").replace("South Korea - ", "")

        stations.append(
            {
                "statId": f"TESLA-{site.get('id')}",
                "statNm": station_name,
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
