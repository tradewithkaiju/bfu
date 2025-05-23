import pandas as pd
import requests

def fetch_ohlcv(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
    ])
    df["close"] = pd.to_numeric(df["close"])
    return df

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def fully_fanned(df: pd.DataFrame, type_: str, periods: list, candles_confirm=3) -> str:
    c = df["close"]
    if type_ == 'ema':
        ma1 = calculate_ema(c, periods[0])
        ma2 = calculate_ema(c, periods[1])
        ma3 = calculate_ema(c, periods[2])
    else:
        ma1 = calculate_sma(c, periods[0])
        ma2 = calculate_sma(c, periods[1])
        ma3 = calculate_sma(c, periods[2])

    last = pd.DataFrame({
        'ma1': ma1[-candles_confirm:].values,
        'ma2': ma2[-candles_confirm:].values,
        'ma3': ma3[-candles_confirm:].values
    })

    is_bull = all(row['ma1'] > row['ma2'] > row['ma3'] for _, row in last.iterrows())
    is_bear = all(row['ma1'] < row['ma2'] < row['ma3'] for _, row in last.iterrows())

    print(f"\nDebug for {type_.upper()} {periods} on last {candles_confirm} candles:")
    print(last)

    if is_bull:
        return 'bullish'
    elif is_bear:
        return 'bearish'
    else:
        return 'neutral'

# === Run analysis on ARKMUSDT.P === #
symbol = "ARKMUSDT.P"
candles_confirm = 3

intervals = {
    '15m': {'type': 'ema', 'periods': [21, 55, 100]},
    '1h':  {'type': 'ema', 'periods': [21, 55, 100]},
    '4h':  {'type': 'sma', 'periods': [7, 30, 100]}
}

results = {}
for tf, cfg in intervals.items():
    df = fetch_ohlcv(symbol, tf)
    trend = fully_fanned(df, cfg['type'], cfg['periods'], candles_confirm)
    results[tf] = trend

print("\n🔍 Trend Check Summary for ARKMUSDT.P:")
for tf, trend in results.items():
    print(f"{tf}: {trend}")
