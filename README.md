# Equity RRG — 주식 로테이션 그래프

S&P 500 섹터·스타일 ETF를 상대순환도(RRG)로 그리는 정적 웹앱.
yfinance로 데이터를 만들고(`build_data.py`), 브라우저에서 ECharts로 렌더한다.
GitHub Actions가 매일 데이터를 갱신해 GitHub Pages로 배포한다.

- **X축** = RSI(상대강도), 기준선 50 — **고정 20~80**
- **Y축** = S&P 500 대비 초과성과 %(모멘텀), 기준선 0 — **고정 −30~+30**
- 수익률 기간: **63영업일(약 3개월)**, RSI: **와일더 14일**
- 계산은 **일별**, 차트 표시는 **주간(금요일 샘플링)**
- 프론트 적재 이력: **최근 5년**
- 꼬리(창) 드래그 · 꼬리 길이 슬라이더/직접입력(1~30, 기본 4) · 섹터 체크박스 · 재생(Animate) · 곡선 스무딩 · 모바일 대응

## 사분면 정의

| 위치 | RSI | 초과성과 | 이름 | 색 |
|---|---|---|---|---|
| 우상 | ≥50 | ≥0 | 1사분면 Leading | 초록 |
| 좌상 | <50 | ≥0 | 2사분면 Improving | 파랑 |
| 좌하 | <50 | <0 | 3사분면 Lagging | 빨강 |
| 우하 | ≥50 | <0 | 4사분면 Weakening | 노랑 |

표준 수학 사분면 번호(반시계)를 따르며, 하단 설명문의 Leading/Improving/Lagging/Weakening 매핑과 일치한다.

## 폴더 구조

```
equity-rrg/
├─ build_data.py                 # yfinance -> docs/data.json
├─ requirements.txt              # pandas, yfinance
├─ docs/                         # GitHub Pages 루트 (여기만 배포됨)
│  ├─ index.html                 # RRG 차트 (data.json을 fetch)
│  ├─ echarts.min.js             # ECharts 5.5.1 동봉 (Apache-2.0, CDN 불필요)
│  └─ data.json                  # build_data.py 산출물 (CI가 매일 재생성)
└─ .github/workflows/deploy.yml  # 매일 배치 + Pages 배포
```

> `docs/index.html`은 반드시 **data.json을 fetch하는 20KB짜리 버전**이어야 한다.
> 데이터를 인라인한 1MB대 "프리뷰" 파일을 올리면 CI가 data.json을 갱신해도 화면이 바뀌지 않는다.

## 데이터 파이프라인 (build_data.py)

Updated.ipynb 산식을 그대로 따른다.

1. 13개 ETF 종가(auto_adjust) 수집 → outer join → **ffill**(거래일 불일치·휴장일 보정)
2. `pct_change(RETURN_DAYS) * 100` — 63영업일 수익률 %
3. **와일더 RSI**: 첫 14구간 SMA 시딩 후 `ewm(alpha=1/14, adjust=False)`
4. 초과성과 = 각 시리즈 수익률 − S&P 500(SPY) 수익률 → 12개 시리즈
5. 결과를 **주간(W-FRI) 샘플링**, 최근 5년만 `docs/data.json` 저장

티커: SPY(벤치마크), IYE·IYM·IYJ·IYC·IYK·IYH·IYF·IYW·IYZ·IDU, VOOG, VOOV

환경변수로 튜닝: `START`(기본 2015-01-01), `RESAMPLE`(기본 `W-FRI`, ""=일간),
`HISTORY_YEARS`(기본 5), `RSI_N`(기본 14), `RETURN_DAYS`(기본 63).

로컬 실행:
```bash
pip install -r requirements.txt
python build_data.py            # docs/data.json 생성
```

## 로컬 미리보기

`fetch('data.json')`이 `file://`에선 CORS로 막히므로 로컬 서버로 확인:
```bash
cd docs && python -m http.server 8000   # http://localhost:8000
```

## 배포 (GitHub Actions + Pages)

1. repo Settings → Pages → Source: **GitHub Actions**
2. `main`에 push (또는 Actions 탭 수동 실행, 또는 매일 cron)
3. `deploy.yml`이 `build_data.py` 실행 → `docs/` 배포 → `https://<사용자>.github.io/<repo>/`

cron `0 22 * * *`(UTC) = **매일 07:00 KST**. 주간 데이터라 점이 새로 찍히는 건 주 1회지만,
형성 중인 주의 점은 매일 최신 종가로 갱신된다.

## 주의사항

- **고정 축 클리핑.** RSI 20~80 / 초과성과 ±30을 벗어나는 값은 화면에 그려지지 않는다.
  현재 데이터에서 범위 밖 포인트는 약 0.7%(RSI 최대 85.4, 초과성과 최대 48.9 등 일부 극단값).
- **부동산 섹터 없음.** Updated.ipynb 티커 목록에 부동산(IYR 등)이 없어 12개 시리즈다.
- **StockCharts 정확 재현 아님.** JdK RS-Ratio/RS-Momentum은 RRG Research의 비공개·상표 방식.
- **Public 배포 = data.json 공개.** yfinance 파생 시세라 통상 문제없지만, 비공개가 필요하면 private repo 검토.
- **yfinance는 Yahoo 비공식 API.** 스키마 변경·레이트리밋으로 실패할 수 있어 최신 버전 사용(requirements 버전 미고정).

## 차트 라이브러리

ECharts 5.5.1 (Apache-2.0) 동봉 — 상업적 이용 무료, 외부 CDN 의존 없음.
