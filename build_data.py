# -*- coding: utf-8 -*-
"""
build_data.py
-------------
yfinance로 S&P 500 섹터/스타일 지수를 받아 RRG용 docs/data.json 생성.

핵심(사용자 확정):
  · 일별 종가를 먼저 주간(금요 종가)으로 리샘플한 뒤,
    그 "주간 종가" 위에서 RSI(14주)와 1년(52주) 초과수익을 계산한다.
  · 프론트에는 최근 HISTORY_YEARS년(기본 10년)만 담는다.

축(프론트와 동일): X = RSI(모멘텀), Y = 1년 초과수익률 %(상대강도). 기준선 X=50 / Y=0.

환경변수로 튜닝 가능:
  START(기본 2000-01-01), RESAMPLE(기본 W-FRI; 빈 문자열이면 일간),
  HISTORY_YEARS(기본 10), RSI_N(기본 14)

의존성: pandas, yfinance
실행: python build_data.py
"""

import os
import json
import datetime as dt
from pathlib import Path

import pandas as pd
import yfinance as yf

# S&P500 섹터 지수 + 스타일 ETF(Growth/Value)
TICKERS = {
    "S&P 500": "^GSPC",
    "에너지": "^GSPE",
    "소재": "^SP500-15",
    "산업재": "^SP500-20",
    "경기소비재": "^SP500-25",
    "필수소비재": "^SP500-30",
    "헬스케어": "^SP500-35",
    "금융": "^SP500-40",
    "IT": "^SP500-45",
    "커뮤니케이션": "^SP500-50",
    "유틸리티": "^SP500-55",
    "부동산": "^SP500-60",
    "Growth": "VOOG",
    "Value": "VOOV",
}
BENCH = "S&P 500"

START         = os.environ.get("START", "2000-01-01")
RESAMPLE      = os.environ.get("RESAMPLE", "W-FRI")   # 주간(금요 종가). ""=일간(거래일)
HISTORY_YEARS = float(os.environ.get("HISTORY_YEARS", "10"))
RSI_N         = int(os.environ.get("RSI_N", "14"))

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "docs" / "data.json"


def fetch_close(ticker, tries=3):
    """단일 티커 종가 시계열(auto-adjust). yfinance 버전별 MultiIndex 방어."""
    last_err = None
    for _ in range(tries):
        try:
            df = yf.download(ticker, start=START, progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                close = df["Close"]
                if isinstance(close, pd.DataFrame):     # 단일 티커인데 MultiIndex인 경우
                    close = close.iloc[:, 0]
                return close.astype(float).dropna()
        except Exception as e:                          # noqa: BLE001
            last_err = e
    raise RuntimeError(f"다운로드 실패: {ticker} ({last_err})")


def rsi_ewm(close, n):
    """Wilder식 RSI(EWM 평활). 사용자 코드와 동일 로직, 입력은 (주간) 종가."""
    delta = close.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gain = gains.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = losses.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(close.notna())


def one_year_return_pct(close):
    """1년 전(달력 기준) 종가 대비 수익률 %. 리샘플된 인덱스 위에서 동작."""
    prev = close.reindex(close.index - pd.DateOffset(years=1), method="ffill")
    prev.index = close.index
    return (close / prev - 1) * 100


def main():
    ann = pd.DataFrame()   # 1년 수익률 %
    rsi = pd.DataFrame()   # RSI

    for sector, ticker in TICKERS.items():
        close = fetch_close(ticker)
        if RESAMPLE:                                    # ⭐ 먼저 주간으로 리샘플
            close = close.resample(RESAMPLE).last().dropna()
        ann[sector] = one_year_return_pct(close)
        rsi[sector] = rsi_ewm(close, RSI_N)

    # 초과성과 = 각 섹터 1년수익 - 벤치마크(S&P500) 1년수익
    excess = ann.sub(ann[BENCH], axis=0).drop(columns=BENCH)
    rsi_x  = rsi.drop(columns=BENCH)
    names  = list(excess.columns)                       # 13개 시리즈

    # 최근 N년 컷
    idx = excess.index
    if HISTORY_YEARS:
        cutoff = idx.max() - pd.DateOffset(years=int(HISTORY_YEARS))
        idx = idx[idx >= cutoff]

    x = rsi_x.reindex(idx)
    y = excess.reindex(idx)

    dates = [d.date().isoformat() for d in idx]
    series, xs, ys = [], [], []
    for name in names:
        xc, yc = x[name], y[name]
        pts = []
        for d in idx:
            xv, yv = xc.loc[d], yc.loc[d]
            if pd.isna(xv) or pd.isna(yv):
                pts.append(None)
            else:
                pts.append([round(float(xv), 4), round(float(yv), 4)])
                xs.append(float(xv)); ys.append(float(yv))
        series.append({"name": name, "points": pts})

    if not xs:
        raise RuntimeError("유효 데이터가 없습니다. START/HISTORY_YEARS 확인 필요.")

    def padded(vals, center, r=0.06):
        lo, hi = min(vals + [center]), max(vals + [center])
        span = hi - lo
        pad = span * r if span > 0 else 1.0
        return round(lo - pad, 2), round(hi + pad, 2)

    x_min, x_max = padded(xs, 50.0)
    y_min, y_max = padded(ys, 0.0)

    out = {
        "meta": {
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": "yfinance",
            "frequency": "weekly" if RESAMPLE else "daily",
            "history_years": HISTORY_YEARS,
            "x_metric": "RSI (모멘텀)",
            "y_metric": "1년 초과수익률 % (상대강도)",
            "x_center": 50.0, "y_center": 0.0,
            "x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
            "n_weeks": len(dates), "n_series": len(names),
        },
        "dates": dates,
        "series": series,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # 용량 최소화(공백 제거) — 프론트 로딩 속도 우선
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[완료] {OUT}")
    print(f"       {len(names)}개 시리즈 x {len(dates)}주 | {dates[0]} ~ {dates[-1]}")
    print(f"       X(RSI) {x_min}~{x_max} / Y(초과수익) {y_min}~{y_max}")


if __name__ == "__main__":
    main()
