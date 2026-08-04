"""docs/data/chargers.geojson 파일의 읽기/쓰기, station dict <-> feature 변환,
지역(zcode)/테슬라 단위의 부분 교체를 담당한다.

이 모듈은 API를 전혀 모른다 — GeoJSON 파일 자체의 구조만 다룬다.
"""
import json
import os

GEOJSON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "data", "chargers.geojson")
)


def load_geojson():
    if not os.path.exists(GEOJSON_PATH):
        return {"type": "FeatureCollection", "features": []}
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_geojson(geojson):
    os.makedirs(os.path.dirname(GEOJSON_PATH), exist_ok=True)
    with open(GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)


def station_to_feature(station):
    lat, lng = station["lat"], station["lng"]
    props = {k: v for k, v in station.items() if k not in ("lat", "lng")}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": props,
    }


def replace_regions(geojson, zcodes, stations):
    """zcodes에 해당하는 기존 feature를 전부 제거하고 새 station 목록으로 교체한다.
    다른 지역의 feature는 건드리지 않는다 (요일별 지역 로테이션의 핵심 동작).
    """
    zcode_set = set(zcodes)
    kept = [f for f in geojson["features"] if f["properties"].get("zcode") not in zcode_set]
    fresh = [station_to_feature(s) for s in stations]
    geojson["features"] = kept + fresh
    return geojson


def replace_tesla(geojson, tesla_stations):
    """isTesla=True인 기존 feature를 전부 제거하고 새 목록으로 교체한다."""
    kept = [f for f in geojson["features"] if not f["properties"].get("isTesla")]
    fresh = [station_to_feature(s) for s in tesla_stations]
    geojson["features"] = kept + fresh
    return geojson
