import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
import ta
from ta.trend import EMAIndicator, SMAIndicator
if 'scan_results' not in st.session_state:
    st.session_state.scan_results = {
        'bullish': [],
        'bearish': [],
        'scan_time': None
    }

# === CONFIG ===
BASE_URL = "https://fapi.binance.com"
TEST_MODE = False  # Set to False for full scan
TEST_SYMBOLS_COUNT = 5  # Number of symbols to scan in test mode

# === MOVING AVERAGE UTILS ===
def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return EMAIndicator(close=df['close'], window=period).ema_indicator()

def calculate_sma(df: pd.DataFrame, period: int) -> pd.Series:
    return SMAIndicator(close=df['close'], window=period).sma_indicator()

def fully_fanned(df: pd.DataFrame, type_: str, periods: list) -> str:
    if type_ == 'ema':
        ma1 = calculate_ema(df, periods[0])
        ma2 = calculate_ema(df, periods[1])
        ma3 = calculate_ema(df, periods[2])
    else:
        ma1 = calculate_sma(df, periods[0])
        ma2 = calculate_sma(df, periods[1])
        ma3 = calculate_sma(df, periods[2])

    # Only check the most recent candle
    last_ma1 = ma1.iloc[-1]
    last_ma2 = ma2.iloc[-1]
    last_ma3 = ma3.iloc[-1]

    if last_ma1 > last_ma2 > last_ma3:
        return 'bullish'
    elif last_ma1 < last_ma2 < last_ma3:
        return 'bearish'
    else:
        return 'neutral'

# === BINANCE API UTILS ===
def get_futures_symbols():
    res = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo").json()
    symbols = [
        s['symbol']
        for s in res['symbols']
        if s['contractType'] == 'PERPETUAL'
        and s['quoteAsset'] == 'USDT'
        and s['status'] == 'TRADING'
        and not s['symbol'].endswith('BUSD')
    ]
    return symbols[:TEST_SYMBOLS_COUNT] if TEST_MODE else symbols

def fetch_ohlcv(symbol, interval, limit=150):
    try:
        url = f"{BASE_URL}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        st.error(f"Error fetching data for {symbol}: {str(e)}")
        return None

def classify_token(symbol):
    try:
        m15 = fetch_ohlcv(symbol, "15m")
        if m15 is None:
            return 'neutral'
            
        h1 = fetch_ohlcv(symbol, "1h")
        if h1 is None:
            return 'neutral'

        m15_trend = fully_fanned(m15, 'ema', [21, 55, 100])
        h1_trend = fully_fanned(h1, 'sma', [7, 30, 100])

        if m15_trend == h1_trend and m15_trend != 'neutral':
            return m15_trend
        return 'neutral'
    except Exception as e:
        st.error(f"Error classifying {symbol}: {str(e)}")
        return 'neutral'

# === MAIN SCAN FUNCTION ===
def run_scanner():
    bullish, bearish = [], []
    symbols = get_futures_symbols()

    progress_bar = st.progress(0)
    progress = st.progress(0, text="Scanning...")
    live_bullish_box = st.empty()
    live_bearish_box = st.empty()

    for i, symbol in enumerate(symbols):
        trend = classify_token(symbol)

        if trend == 'bullish':
            bullish.append(symbol)
        elif trend == 'bearish':
            bearish.append(symbol)

        # Update live display
        live_bullish_box.markdown(f"**📈 Live Bullish Tokens** ({len(bullish)}): `{', '.join(bullish)}`")
        live_bearish_box.markdown(f"**📉 Live Bearish Tokens** ({len(bearish)}): `{', '.join(bearish)}`")

        progress.progress((i + 1) / len(symbols), text=f"Scanning {symbol}...")
        time.sleep(0.2)

    # Store results in session state
    st.session_state.scan_results = {
        'bullish': bullish,
        'bearish': bearish,
        'scan_time': datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    }
    return bullish, bearish

# === STREAMLIT APP ===
st.set_page_config(page_title="Binance Trend Scanner", layout="wide")
st.title("📈 Binance Futures Trend Scanner")

st.markdown("""
Scan for trending Binance USDT Perpetual tokens using:
- 21/55/100 EMAs on 15m
- 7/30/100 SMAs on 1h
- Fully fanned logic for up/down trend detection
""")

# 🚀 Full Scan Button
if st.button("🚀 Run Trend Scan Now"):
    run_scanner()

# Only show results and exports if we have scan data
if st.session_state.scan_results['bullish'] or st.session_state.scan_results['bearish']:
    bullish = st.session_state.scan_results['bullish']
    bearish = st.session_state.scan_results['bearish']
    now = st.session_state.scan_results['scan_time']

    st.subheader("✅ Scan Results")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"**📈 Bullish Tokens**: {len(bullish)}")
        st.write([f"{s}.P" for s in bullish] or "None")
        
    with col2:
        st.markdown(f"**📉 Bearish Tokens**: {len(bearish)}")
        st.write([f"{s}.P" for s in bearish] or "None")

    # TradingView-friendly exports
    st.subheader("📋 Exports")
    
    # Create exports without triggering rerun
    tv_watchlist = "\n".join([f"BINANCE:{s}.P" for s in sorted(bullish + bearish)])
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.download_button(
            label="📋 Download TradingView Watchlist",
            data=tv_watchlist,
            file_name=f"kaiju_bfu_watchlist_{now}.txt",
            mime="text/plain",
            key="tv_download"  # Unique key to prevent rerun
        )
    
    with col2:
        minimal_data = {
            "Symbol": [f"{s}.P" for s in bullish + bearish],
            "Trend": ["Bullish"]*len(bullish) + ["Bearish"]*len(bearish)
        }
        minimal_df = pd.DataFrame(minimal_data)
        csv = minimal_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="📁 Download CSV",
            data=csv,
            file_name=f"kaiju_bfu_watchlist_{now}.csv",
            mime="text/csv",
            key="csv_download"  # Unique key to prevent rerun
        )