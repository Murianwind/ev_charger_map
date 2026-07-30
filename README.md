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
python scripts/fetch_chargers.py
```

`docs/data/chargers.geojson`이 갱신되며, `docs/index.html`을 브라우저로 열거나
`python -m http.server`로 `docs/` 디렉터리를 서빙해 바로 확인할 수 있습니다.

## 참고

- `chgerType` 필터는 `scripts/fetch_chargers.py`의 `ALLOWED_CHGER_TYPES`에서
  조정할 수 있습니다.
- API 페이지네이션은 `numOfRows=9999` 기준으로 전체 건수만큼 자동 반복 호출합니다.
