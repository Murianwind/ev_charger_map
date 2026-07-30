# 전국 완속충전기 지도

한국환경공단 `getChargerInfo` API에서 전국 충전기 데이터를 받아 아래 조건으로
필터링한 뒤, GitHub Pages 지도(`docs/index.html`)에 표시합니다.

## 필터 조건

| 조건 | 값 |
|---|---|
| 이용자 제한 | `limitYn == "N"` (제한 없음) |
| 주차료 | `parkingFree == "Y"` (무료) |
| 충전기 타입 | `chgerType`가 `02`(AC완속) / `09`(NACS) / `10`(DC콤보+NACS) |
| 삭제 여부 | `delYn != "Y"` |

같은 충전소(`statId`)에 속한 충전기는 지도에서 마커 하나로 묶이고,
각 충전기 상태(`stat`)는 팝업 안에서 개별적으로 구분 표시됩니다
(2: 사용가능 = 초록, 3: 충전중 = 주황, 그 외 = 회색).

`limitYn`이 `N`이어도 `limitDetail`에 텍스트가 남아있는 경우, 팝업 하단에
"참고" 메모로 그대로 노출됩니다. 추후 필터 조건을 보강할 때 참고하기 위한
정보이며 현재는 필터링에 사용하지 않습니다.

## API 호출 횟수 설계 (일일 1,000회 제한 대응)

data.go.kr 개발계정은 하루 1,000건까지만 호출됩니다. 이 저장소는 두 개의
워크플로로 나눠서 이 한도 안에서 상태를 최대한 자주 갱신합니다.

| 워크플로 | 사용 오퍼레이션 | 주기 | 특징 | 대략적 호출 수 |
|---|---|---|---|---|
| `update-chargers.yml` | `getChargerInfo` | 하루 1회 | 위치/타입/이용조건 등 전체 정보 재수집 (`numOfRows=9999`로 페이지네이션) | 전국 데이터 규모 기준 약 50~90회/일 |
| `update-status.yml` | `getChargerStatus` | 10분 간격 | `period`(분) 파라미터로 **그 시간 안에 상태가 바뀐 충전기만** 델타로 받아옴 — 전체를 매번 다시 받지 않음 | 보통 1회(많아도 몇 회)/호출, 하루 약 150~300회 |

`getChargerStatus`는 실제로 최근 N분 내 상태 변경분만 돌려주는 델타 피드라서,
"방금 바뀐 것만" 가볍게 받아 `docs/data/chargers.geojson`에 병합하는 식으로
구현했습니다 (`fetch_status.py`). 10분 주기로 돌리면서 `period=10`으로 겹치게
잡아, 실행이 몇 분 밀리거나 한 번 실패해도 변경 이력이 비지 않게 했습니다.

두 워크플로를 합쳐도 하루 약 200~400회 수준이라 1,000회 한도에 여유가 있고,
필요하면 상태 갱신 주기를 5분으로 더 좁혀도 됩니다. 두 워크플로가 같은
`docs/data/chargers.geojson` 파일에 동시에 커밋하는 걸 막기 위해
`concurrency: group: ev-charger-data`로 묶어 순차 실행되게 했고, 커밋 전에
`git pull --rebase`를 넣어 충돌을 줄였습니다.

나중에 트래픽이 더 필요하면 공공데이터포털에서 활용사례 등록 후 트래픽 증가
신청도 가능합니다.

## 지도 동작 (반경 50km 표출)

- 지도를 열면 브라우저 위치 권한을 요청해 **현재 위치 기준 반경 50km** 안의
  충전소만 우선 표출합니다.
- 위치 권한을 거부했거나 가져올 수 없으면 전국 데이터를 그대로 보여줍니다.
- 지도를 드래그/확대·축소한 뒤 이동이 끝나고 1.5초가 지나면, **새로운 지도
  중심 기준 반경 50km**로 다시 필터링해서 표출합니다 (`docs/index.html`의
  `MOVE_SETTLE_DELAY_MS`에서 시간 조정 가능). 이미 받아둔 전체 GeoJSON을
  클라이언트에서 거리 계산(Haversine)으로 걸러내는 방식이라 추가 API 호출은
  발생하지 않습니다.

## 설정 방법

1. **API 키 발급**: [data.go.kr](https://www.data.go.kr) 로그인 및 회원가입 후
   `한국환경공단_전기자동차 충전소 정보` 활용신청 → 승인되면 서비스키 발급
2. **GitHub Secret 등록**: 저장소 Settings → Secrets and variables → Actions →
   `EV_SERVICE_KEY` 이름으로 발급받은 서비스키(디코딩 키) 등록
3. **GitHub Pages 활성화**: Settings → Pages → Source를 `main` 브랜치의
   `/docs` 폴더로 설정
4. **워크플로 실행**: Actions 탭 → `Update EV Charger Data` → `Run workflow`로
   수동 실행 (이후에는 매일 자동 실행)
5. 몇 분 후 GitHub Pages 주소로 접속하면 실제 데이터가 반영된 지도가 보입니다.

## 로컬 테스트

```bash
export EV_SERVICE_KEY="발급받은_서비스키"

# 전체 정보 (위치/타입/이용조건 등)
python scripts/fetch_chargers.py

# 최근 10분 내 상태 변경분만 반영 (전체 재수집 X)
python scripts/fetch_status.py
```

`docs/data/chargers.geojson`이 갱신되며, `docs/index.html`을 브라우저로 열거나
`python -m http.server`로 `docs/` 디렉터리를 서빙해 바로 확인할 수 있습니다.
(로컬 파일을 `file://`로 직접 열면 브라우저 정책상 위치 정보 요청이나 fetch가
막힐 수 있어 `http.server` 사용을 권장합니다.)

## 참고

- `chgerType` 필터는 `scripts/fetch_chargers.py`의 `ALLOWED_CHGER_TYPES`에서
  조정할 수 있습니다.
- API 페이지네이션은 `numOfRows=9999` 기준으로 전체 건수만큼 자동 반복 호출합니다.
