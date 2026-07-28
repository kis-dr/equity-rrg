# -*- coding: utf-8 -*-
"""
build_data.py
-------------
yfinance로 S&P 500 섹터/스타일 ETF를 받아 RRG용 docs/data.json 생성.

산식(Updated.ipynb 기준):
  1) 티커별 종가(auto_adjust) 수집 -> outer join -> ffill (휴장일/거래일 불일치 보정)
  2) RETURN_DAYS 영업일 수익률 % = close.pct_change(RETURN_DAYS) * 100
  3) RSI = 와일더 평활 (첫 n구간 SMA 시딩 후 ewm(alpha=1/n, adjust=False))
  4) 초과성과 % = 각 시리즈 수익률 - S&P 500 수익률
  5) 위 결과를 주간(금요일)으로 샘플링하고 최근 HISTORY_YEARS년만 저장

  · 계산은 노트북과 동일하게 "일별"로 수행하고, 차트 표시용으로만 주간 샘플링합니다.
    (RETURN_DAYS=63 ~ 3개월, RSI_N=14일)

축: X = RSI(모멘텀), Y = 초과성과 %(상대강도). 기준선 X=50 / Y=0.
프론트 축은 고정(RSI 20~80, 초과성과 -30~+30)이며 이 값은 data.json meta에 담습니다.

환경변수:
  START(기본 2015-01-01), RESAMPLE(기본 W-FRI, ""=일간),
  HISTORY_YEARS(기본 5), RSI_N(기본 14), RETURN_DAYS(기본 63)

의존성: pandas, yfinance
"""

import os
import json
import datetime as dt
from pathlib import Path

import pandas as pd
import yfinance as yf

# -- 티커 (Updated.ipynb과 동일) --------------------------------------------
TICKERS = {
    "S&P 500": "SPY",
    "에너지": "IYE",
    "소재": "IYM",
    "산업재": "IYJ",
    "경기소비재": "IYC",
    "필수소비재": "IYK",
    "헬스케어": "IYH",
    "금융": "IYF",
    "IT": "IYW",
    "커뮤니케이션": "IYZ",
    "유틸리티": "IDU",
    "Growth": "VOOG",
    "Value": "VOOV",
}
BENCH = "S&P 500"

START         = os.environ.get("START", "2015-01-01")
RESAMPLE      = os.environ.get("RESAMPLE", "W-FRI")   # 주간(금요 종가). ""=일간
HISTORY_YEARS = float(os.environ.get("HISTORY_YEARS", "5"))
RSI_N         = int(os.environ.get("RSI_N", "14"))
RETURN_DAYS   = int(os.environ.get("RETURN_DAYS", "63"))   # 3개월 ~ 63영업일

# 고정 축 범위 (요건: RSI 20~80, 초과성과 -30~+30)
X_MIN, X_MAX = 20.0, 80.0
Y_MIN, Y_MAX = -30.0, 30.0

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "docs" / "data.json"


def fetch_close(ticker: str, tries: int = 3) -> pd.Series:
    """단일 티커 종가 시계열. yfinance 버전별 MultiIndex 방어 + 재시도."""
    last_err = None
    for _ in range(tries):
        try:
            df = yf.download(ticker, start=START, progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                close = df["Close"]
                if isinstance(close, pd.DataFrame):      # 단일 티커인데 MultiIndex인 경우
                    close = close.iloc[:, 0]
                return close.astype(float).dropna()
        except Exception as e:                            # noqa: BLE001
            last_err = e
    raise RuntimeError(f"다운로드 실패: {ticker} ({last_err})")


def calculate_rsi_wilder(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """와일더 평활 RSI. 첫 n구간은 SMA로 시딩 (Updated.ipynb과 동일)."""
    delta = df.diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    sma_gains = gains.rolling(window=n, min_periods=n).mean()
    sma_losses = losses.rolling(window=n, min_periods=n).mean()

    avg_gains = gains.copy()
    avg_losses = losses.copy()

    avg_gains.iloc[:n] = sma_gains.iloc[:n]
    avg_losses.iloc[:n] = sma_losses.iloc[:n]

    avg_gains = avg_gains.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_losses = avg_losses.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

    rs = avg_gains / avg_losses
    return 100 - (100 / (1 + rs))


def main() -> None:
    # -- 1. 종가 수집 및 통합 ------------------------------------------------
    close_list = []
    for sector, ticker in TICKERS.items():
        close = fetch_close(ticker)
        close.name = sector
        close_list.append(close)

    close_df = pd.concat(close_list, axis=1)
    close_df = close_df.ffill()                # 거래일 불일치/휴장일 보정

    # -- 2. 영업일 기준 수익률 (%) -------------------------------------------
    ret_df = close_df.pct_change(RETURN_DAYS) * 100

    # -- 3. RSI (와일더) -----------------------------------------------------
    rsi_df = calculate_rsi_wilder(close_df, n=RSI_N)

    # -- 4. S&P 500 대비 초과성과 (%) ----------------------------------------
    excess_df = ret_df.sub(ret_df[BENCH], axis=0).drop(columns=BENCH)
    rsi_x = rsi_df.drop(columns=BENCH)
    names = list(excess_df.columns)

    # -- 5. 주간 샘플링 + 최근 N년 컷 ----------------------------------------
    if RESAMPLE:
        rsi_x = rsi_x.resample(RESAMPLE).last()
        excess_df = excess_df.resample(RESAMPLE).last()

    idx = excess_df.index
    if HISTORY_YEARS:
        cutoff = idx.max() - pd.DateOffset(years=int(HISTORY_YEARS))
        idx = idx[idx >= cutoff]

    x = rsi_x.reindex(idx)
    y = excess_df.reindex(idx)

    # 두 축 모두 값이 있는 주만 유지
    valid = x.notna().any(axis=1) & y.notna().any(axis=1)
    idx = idx[valid]
    x, y = x.reindex(idx), y.reindex(idx)

    dates = [d.date().isoformat() for d in idx]
    series, n_out = [], 0
    for name in names:
        xc, yc = x[name], y[name]
        pts = []
        for d in idx:
            xv, yv = xc.loc[d], yc.loc[d]
            if pd.isna(xv) or pd.isna(yv):
                pts.append(None)
                continue
            xv, yv = float(xv), float(yv)
            pts.append([round(xv, 4), round(yv, 4)])
            if not (X_MIN <= xv <= X_MAX and Y_MIN <= yv <= Y_MAX):
                n_out += 1
        series.append({"name": name, "points": pts})

    n_pts = sum(1 for s in series for p in s["points"] if p)
    if not n_pts:
        raise RuntimeError("유효 데이터가 없습니다. START/HISTORY_YEARS 확인 필요.")

    out = {
        "meta": {
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": "yfinance",
            "frequency": "weekly" if RESAMPLE else "daily",
            "history_years": HISTORY_YEARS,
            "return_days": RETURN_DAYS,
            "rsi_n": RSI_N,
            "x_metric": "RSI (모멘텀)",
            "y_metric": f"{RETURN_DAYS}영업일 초과성과 % (상대강도)",
            "x_center": 50.0, "y_center": 0.0,
            "x_min": X_MIN, "x_max": X_MAX,
            "y_min": Y_MIN, "y_max": Y_MAX,
            "n_weeks": len(dates), "n_series": len(names),
        },
        "dates": dates,
        "series": series,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"[완료] {OUT}")
    print(f"       {len(names)}개 시리즈 x {len(dates)}주 | {dates[0]} ~ {dates[-1]}")
    print(f"       수익률 {RETURN_DAYS}영업일 / RSI {RSI_N}일 / 축 고정 X[{X_MIN},{X_MAX}] Y[{Y_MIN},{Y_MAX}]")
    print(f"       고정 축 범위 밖 포인트: {n_out} / {n_pts} ({n_out / n_pts * 100:.1f}%)")


if __name__ == "__main__":
    main()
