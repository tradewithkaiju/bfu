import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import ta
from ta.trend import EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from streamlit_autorefresh import st_autorefresh

# Initialize session state
if 'scan_results' not in st.session_state:
    st.session_state.scan_results = {
        'bullish_in_range': [],
        'bullish_range_break': [],
        'bearish_in_range': [],
        'bearish_range_break': [],
        'scan_time': None,
        'current_progress': 0,
        'current_symbol': '',
        'live_results': {
            'bullish_in_range': [],
            'bullish_range_break': [],
            'bearish_in_range': [],
            'bearish_range_break': []
        }
    }

# === CONFIG ===
BASE_URL = "https://fapi.binance.com"
TEST_SYMBOLS_COUNT = 20

# === MOVING AVERAGE UTILS ===
def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return EMAIndicator(close=df['close'], window=period).ema_indicator()

def calculate_sma(df: pd.DataFrame, period: int) -> pd.Series:
    return SMAIndicator(close=df['close'], window=period).sma_indicator()

def calculate_rsi(df: pd.DataFrame, period: int) -> pd.Series:
    return RSIIndicator(close=df['close'], window=period).rsi()

def fully_fanned(df: pd.DataFrame, type_: str, periods: list) -> str:
    if type_ == 'ema':
        ma1 = calculate_ema(df, periods[0])
        ma2 = calculate_ema(df, periods[1])
        ma3 = calculate_ema(df, periods[2])
    else:
        ma1 = calculate_sma(df, periods[0])
        ma2 = calculate_sma(df, periods[1])
        ma3 = calculate_sma(df, periods[2])

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
def get_futures_symbols(test_mode=False):
    res = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo").json()
    symbols = [
        s['symbol']
        for s in res['symbols']
        if s['contractType'] == 'PERPETUAL'
        and s['quoteAsset'] == 'USDT'
        and s['status'] == 'TRADING'
        and not s['symbol'].endswith('BUSD')
    ]
    return symbols[:TEST_SYMBOLS_COUNT] if test_mode else symbols

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

def classify_token(symbol, apply_momentum_filter=True, apply_rsi_filter=True):
    try:
        # Fetch data for all timeframes
        m15 = fetch_ohlcv(symbol, "15m")
        h1 = fetch_ohlcv(symbol, "1h")
        h4 = fetch_ohlcv(symbol, "4h")
        
        if m15 is None or h1 is None or h4 is None:
            return None

        # Calculate trends
        m15_trend = fully_fanned(m15, 'ema', [21, 55, 100])
        h1_trend = fully_fanned(h1, 'sma', [7, 30, 100])
        h4_trend = fully_fanned(h4, 'sma', [7, 30, 100])

        # Calculate RSI values
        m15_rsi = calculate_rsi(m15, 14).iloc[-1]
        h1_rsi = calculate_rsi(h1, 14).iloc[-1]
        h4_rsi = calculate_rsi(h4, 14).iloc[-1]

        # === Trend (Momentum) Filtering ===
        if apply_momentum_filter:
            if not (m15_trend == h1_trend and m15_trend in ['bullish', 'bearish']):
                return None
        else:
            m15_trend = h1_trend = 'neutral'  # fallback if filter is off

        # === RSI Filtering ===
        if apply_rsi_filter:
            if m15_trend == h1_trend == 'bullish':
                if (50 <= m15_rsi <= 60) and (50 <= h1_rsi <= 60) and (50 <= h4_rsi <= 60):
                    return 'bullish_in_range'
                elif (60 <= m15_rsi <= 70) and (60 <= h1_rsi <= 70) and (h4_rsi < 70):
                    return 'bullish_range_break'
            elif m15_trend == h1_trend == 'bearish':
                if (40 <= m15_rsi <= 50) and (40 <= h1_rsi <= 50) and (40 <= h4_rsi <= 50):
                    return 'bearish_in_range'
                elif (30 <= m15_rsi <= 40) and (30 <= h1_rsi <= 40) and (h4_rsi > 30):
                    return 'bearish_range_break'
            return None
        else:
            # Return categories purely based on trend if RSI is disabled
            if m15_trend == h1_trend == 'bullish':
                return 'bullish_in_range'
            elif m15_trend == h1_trend == 'bearish':
                return 'bearish_in_range'
            return None
    
    except Exception as e:
        st.error(f"Error classifying {symbol}: {str(e)}")
        return None

# Save latest results to disk
def save_latest_results():
    timestamp = st.session_state.scan_results['scan_time']
    for category in ['bullish_in_range', 'bullish_range_break', 'bearish_in_range', 'bearish_range_break']:
        symbols = st.session_state.scan_results[category]
        if symbols:
            txt_data = "\n".join([f"BINANCE:{s}.P" for s in sorted(symbols)])
            csv_data = pd.DataFrame({
                "Symbol": [f"{s}.P" for s in sorted(symbols)],
                "Category": [category.replace('_', ' ').title()] * len(symbols)
            }).to_csv(index=False)

            with open(f"latest_{category}.txt", "w") as f:
                f.write(txt_data)
            with open(f"latest_{category}.csv", "w") as f:
                f.write(csv_data)

#Load latest file
def load_latest_file(category, filetype):
    filename = f"latest_{category}.{filetype}"
    try:
        with open(filename, "r" if filetype == "txt" else "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None

# === MAIN SCAN FUNCTION ===
def run_scanner(apply_momentum_filter=True, apply_rsi_filter=True):
    
    # Clear live results before starting a new scan
    st.session_state.scan_results['live_results'] = {
        'bullish_in_range': [],
        'bullish_range_break': [],
        'bearish_in_range': [],
        'bearish_range_break': []
    }

    symbols = get_futures_symbols(TEST_MODE)
    total_symbols = len(symbols)

    # Initialize live display containers
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Create columns for live results
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.subheader("🐂 Bullish - In Range")
        live_bullish_in_range = st.empty()
    with col2:
        st.subheader("🚀 Bullish - Range Break")
        live_bullish_break = st.empty()
    with col3:
        st.subheader("🐻 Bearish - In Range")
        live_bearish_in_range = st.empty()
    with col4:
        st.subheader("💥 Bearish - Range Break")
        live_bearish_break = st.empty()

    for i, symbol in enumerate(symbols):
        # Update progress
        progress = (i + 1) / total_symbols
        st.session_state.current_progress = progress
        st.session_state.current_symbol = symbol
        progress_bar.progress(progress)
        status_text.text(f"🔍 Scanning {symbol} ({i+1}/{total_symbols})")
        
        # Classify token
        classification = classify_token(symbol, apply_momentum_filter, apply_rsi_filter)
        
        # Update results
        if classification:
            st.session_state.scan_results['live_results'][classification].append(symbol)
            st.session_state.scan_results[classification].append(symbol)
            
            # Update live displays
            live_bullish_in_range.markdown(
                f"`{', '.join(st.session_state.scan_results['live_results']['bullish_in_range'])}`"
                if st.session_state.scan_results['live_results']['bullish_in_range']
                else "None"
            )

            live_bullish_break.markdown(
                f"`{', '.join(st.session_state.scan_results['live_results']['bullish_range_break'])}`"
                if st.session_state.scan_results['live_results']['bullish_range_break']
                else "None"
            )

            live_bearish_in_range.markdown(
                f"`{', '.join(st.session_state.scan_results['live_results']['bearish_in_range'])}`"
                if st.session_state.scan_results['live_results']['bearish_in_range']
                else "None"
            )

            live_bearish_break.markdown(
                f"`{', '.join(st.session_state.scan_results['live_results']['bearish_range_break'])}`"
                if st.session_state.scan_results['live_results']['bearish_range_break']
                else "None"
            )

        
        time.sleep(0.075)  # Rate limiting
    
    # Finalize results
    st.session_state.scan_results['scan_time'] = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    progress_bar.empty()
    save_latest_results()
    status_text.success("✅ Scan completed!")

#Wrap Buttons
def render_download_buttons(label_prefix, data_list, category, timestamp, col):
    with col:
        st.subheader(label_prefix)
        st.write([f"{s}.P" for s in data_list] or "None")

        if data_list:
            txt_data = "\n".join([f"BINANCE:{s}.P" for s in sorted(data_list)])
            csv_data = pd.DataFrame({
                "Symbol": [f"{s}.P" for s in data_list],
                "Category": [category] * len(data_list)
            }).to_csv(index=False).encode('utf-8')

            st.download_button(
                label="📋 TXT Export",
                data=txt_data,
                file_name=f"kaiju_{label_prefix.lower().replace(' ', '_')}_bfuscan_{timestamp}.txt",
                mime="text/plain",
                key=f"{label_prefix.lower().replace(' ', '_')}_txt_{timestamp}"
            )
            st.download_button(
                label="📁 CSV Export",
                data=csv_data,
                file_name=f"kaiju_{label_prefix.lower().replace(' ', '_')}_bfuscan_{timestamp}.csv",
                mime="text/csv",
                key=f"{label_prefix.lower().replace(' ', '_')}_csv_{timestamp}"
            )
        else:
            st.button(f"📋 TXT Export (No Data)", disabled=True, key=f"{label_prefix.lower().replace(' ', '_')}_txt_disabled_{timestamp}")
            st.button(f"📁 CSV Export (No Data)", disabled=True, key=f"{label_prefix.lower().replace(' ', '_')}_csv_disabled_{timestamp}")


# === STREAMLIT APP ===

st.set_page_config(page_title="Binance Trend Scanner", layout="wide")
st.title("📈 Binance Futures Trend Scanner")

st.sidebar.header("🔧 Settings")

# Test mode toggle
TEST_MODE = st.sidebar.checkbox("Test Mode (Limit to 20 tokens)", value=False)

# Filter toggles
apply_momentum_filter = st.sidebar.checkbox("Apply Momentum Filter (MA fans)", value=False)
apply_rsi_filter = st.sidebar.checkbox("Apply RSI Filter", value=True)

st.markdown("""
Scan for trending Binance USDT Perpetual tokens using:
- 21/55/100 EMAs on 15m
- 7/30/100 SMAs on 1h
- RSI filters for precise entry points
""")

# Reset live results on load
if 'scan_results' not in st.session_state:
    st.session_state.scan_results = {}

st.session_state.scan_results['live_results'] = {
    'bullish_in_range': [],
    'bullish_range_break': [],
    'bearish_in_range': [],
    'bearish_range_break': []
}

from streamlit_autorefresh import st_autorefresh

# Get current time
now = datetime.now()

# Compute time until the next 5-minute mark
minutes = now.minute
seconds = now.second

# How many minutes to add to reach next 5-minute mark
minutes_to_next_five = (5 - (minutes % 5)) % 5
seconds_to_next_run = (minutes_to_next_five * 60) - seconds
if seconds_to_next_run <= 0:
    seconds_to_next_run += 300  # Avoid negative or 0 delay

# Refresh interval in milliseconds
refresh_interval_ms = seconds_to_next_run * 1000

# Sync to next 5-minute mark
st_autorefresh(interval=refresh_interval_ms, key="clock_sync_refresh")


# Auto-run on load
run_scanner(apply_momentum_filter, apply_rsi_filter)

# Optional: Manual trigger
if st.button("🔁 Refresh Trend Scan"):
    run_scanner(apply_momentum_filter, apply_rsi_filter)

# Display only live results with download buttons
if st.session_state.scan_results['scan_time']:
    col1, col2, col3, col4 = st.columns(4)
    timestamp = st.session_state.scan_results['scan_time']

    render_download_buttons("🐂 Bullish - In Range", st.session_state.scan_results['bullish_in_range'], "Bullish - In Range", timestamp, col1)
    render_download_buttons("🚀 Bullish - Range Break", st.session_state.scan_results['bullish_range_break'], "Bullish - Range Break", timestamp, col2)
    render_download_buttons("🐻 Bearish - In Range", st.session_state.scan_results['bearish_in_range'], "Bearish - In Range", timestamp, col3)
    render_download_buttons("💥 Bearish - Range Break", st.session_state.scan_results['bearish_range_break'], "Bearish - Range Break", timestamp, col4)