"""카카오 로컬 API(주소 검색)로, 정부 API가 준 좌표가 실제 주소와 맞는지
검증하고 필요하면 보정한다.

한국환경공단 API는 위/경도 값 자체가 틀린 경우가 있다 (예: 주소는 대전인데
좌표는 이천 근방). 매일 갱신하는 지역이 전국이 아니라 하루치 분량(몇백~천
개소 수준)이라, 충전소마다 지오코딩을 해도 카카오 로컬 API의 무료 한도
(하루 30만 건)에 전혀 부담이 없다.

KAKAO_REST_API_KEY 환경변수가 없으면 지오코딩 자체를 건너뛴다(선택 사항 —
설정 안 해도 나머지 파이프라인은 정상 동작하고, gov_charger_api의 대략적인
도(道) 사각형 검증만으로 최소한의 안전망을 유지한다).
"""
import os
import urllib.parse
from math import asin, cos, radians, sin, sqrt

from http_client import fetch_json

KAKAO_GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_COORD2ADDR_URL = "https://dapi.kakao.com/v2/local/geo/coord2address.json"

# 이 거리(km)보다 많이 벌어지면 원본 좌표를 못 믿을 걸로 보고 카카오 좌표로
# 교체한다. GPS 오차나 지오코딩 자체의 오차 범위를 감안한 여유값이다.
MISMATCH_THRESHOLD_KM = 3.0


def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def geocode_address(addr):
    """addr 문자열을 지오코딩해서 (lat, lng)을 반환한다. 키가 없거나
    실패하거나 결과가 없으면 None을 반환한다(호출부가 원본 좌표를 유지하도록).
    """
    key = os.environ.get("KAKAO_REST_API_KEY")
    if not key or not addr:
        return None

    url = f"{KAKAO_GEOCODE_URL}?query={urllib.parse.quote(addr)}"
    try:
        data = fetch_json(url, extra_headers={"Authorization": f"KakaoAK {key}"})
    except Exception:  # noqa: BLE001 - 지오코딩 실패는 전체 실행을 막지 않고 건너뛴다
        return None

    documents = data.get("documents") or []
    if not documents:
        return None

    doc = documents[0]
    try:
        return float(doc["y"]), float(doc["x"])  # 카카오는 x=경도, y=위도
    except (KeyError, TypeError, ValueError):
        return None


def reverse_geocode(lat, lng):
    """좌표를 한글 주소로 변환한다 (도로명주소 우선, 없으면 지번주소).
    키가 없거나 실패하거나 결과가 없으면 None을 반환한다 — 테슬라 슈퍼차저처럼
    영문 주소만 있는 데이터를 한글 주소로 바꿔 표시하기 위한 용도다.
    """
    key = os.environ.get("KAKAO_REST_API_KEY")
    if not key:
        return None

    url = f"{KAKAO_COORD2ADDR_URL}?x={lng}&y={lat}"
    try:
        data = fetch_json(url, extra_headers={"Authorization": f"KakaoAK {key}"})
    except Exception:  # noqa: BLE001 - 지오코딩 실패는 전체 실행을 막지 않고 건너뛴다
        return None

    documents = data.get("documents") or []
    if not documents:
        return None

    doc = documents[0]
    road_address = doc.get("road_address") or {}
    if road_address.get("address_name"):
        return road_address["address_name"]

    address = doc.get("address") or {}
    return address.get("address_name") or None


def verify_and_correct(addr, lat, lng):
    """카카오 지오코딩 결과와 비교해 필요하면 좌표를 교체한다.

    반환값: (최종 lat, 최종 lng, status)
    status:
      - "verified"    : 카카오 결과와 충분히 가까워서 원본 좌표를 그대로 씀
      - "corrected"    : 카카오 좌표로 교체함
      - "unavailable" : 지오코딩 실패(키 미설정/주소 인식 불가 등) — 검증 못 함
    """
    geocoded = geocode_address(addr)
    if geocoded is None:
        return lat, lng, "unavailable"

    glat, glng = geocoded
    if _haversine_km(lat, lng, glat, glng) > MISMATCH_THRESHOLD_KM:
        return glat, glng, "corrected"
    return lat, lng, "verified"
