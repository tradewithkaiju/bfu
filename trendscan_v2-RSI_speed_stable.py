import streamlit as st
import pandas as pd
import asyncio
import aiohttp
from datetime import datetime
import ta
from ta.trend import EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator

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
TEST_MODE = False
TEST_SYMBOLS_COUNT = 5
MAX_CONCURRENT_REQUESTS = 6  # ~6 req/sec = ~360 req/min = safe under 1200 weight/min

# === MOVING AVERAGE UTILS ===
def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return EMAIndicator(close=df['close'], window=period).ema_indicator()

def calculate_sma(df: pd.DataFrame, period: int) -> pd.Series:
    return SMAIndicator(close=df['close'], window=period).sma_indicator()

def calculate_rsi(df: pd.DataFrame, period: int) -> pd.Series:
    return RSIIndicator(close=df['close'], window=period).rsi()

def fully_fanned(df: pd.DataFrame, type_: str, periods: list) -> str:
    try:
        if type_ == 'ema':
            ma1 = calculate_ema(df, periods[0])
            ma2 = calculate_ema(df, periods[1])
            ma3 = calculate_ema(df, periods[2])
        else:
            ma1 = calculate_sma(df, periods[0])
            ma2 = calculate_sma(df, periods[1])
            ma3 = calculate_sma(df, periods[2])

        # Validate that none of the series are too short
        if len(ma1) < 1 or len(ma2) < 1 or len(ma3) < 1:
            return "incomplete"

        last_ma1 = ma1.iloc[-1]
        last_ma2 = ma2.iloc[-1]
        last_ma3 = ma3.iloc[-1]

        # Your custom logic here
        if last_ma1 > last_ma2 > last_ma3:
            return "bullish"
        elif last_ma1 < last_ma2 < last_ma3:
            return "bearish"
        else:
            return "neutral"

    except Exception as e:
        print(f"Error in fully_fanned: {e}")
        return "error"

# === ASYNC BINANCE API UTILS ===
async def get_futures_symbols(session):
    async with session.get(f"{BASE_URL}/fapi/v1/exchangeInfo") as response:
        res = await response.json()
        symbols = [
            s['symbol']
            for s in res['symbols']
            if s['contractType'] == 'PERPETUAL'
            and s['quoteAsset'] == 'USDT'
            and s['status'] == 'TRADING'
            and not s['symbol'].endswith('BUSD')
        ]
        return symbols[:TEST_SYMBOLS_COUNT] if TEST_MODE else symbols

async def fetch_ohlcv(session, symbol, interval, limit=150):
    try:
        url = f"{BASE_URL}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        async with session.get(url, params=params) as response:
            data = await response.json()
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

async def classify_token(session, symbol, progress_bar, status_text, total_symbols, current_index):
    try:
        # Fetch data for all timeframes concurrently
        m15, h1, h4 = await asyncio.gather(
            fetch_ohlcv(session, symbol, "15m"),
            fetch_ohlcv(session, symbol, "1h"),
            fetch_ohlcv(session, symbol, "4h"),
        )
        
        if m15 is None or h1 is None or h4 is None:
            return None

        # Calculate trends
        m15_trend = fully_fanned(m15, 'ema', [21, 55, 100])
        h1_trend = fully_fanned(h1, 'sma', [7, 30, 100])
        h4_trend = fully_fanned(h4, 'sma', [7, 30, 100])

        # Calculate RSI values
        try:
            m15_rsi_series = calculate_rsi(m15, 14)
            h1_rsi_series = calculate_rsi(h1, 14)
            h4_rsi_series = calculate_rsi(h4, 14)

            if m15_rsi_series.empty or h1_rsi_series.empty or h4_rsi_series.empty:
                raise ValueError("RSI series is empty")

            m15_rsi = m15_rsi_series.iloc[-1]
            h1_rsi = h1_rsi_series.iloc[-1]
            h4_rsi = h4_rsi_series.iloc[-1]

        except Exception as e:
            print(f"Skipping symbol due to RSI error: {e}")
            return  # or continue, depending on your structure

        # Check for bullish conditions
        if m15_trend == h1_trend == 'bullish':
            # Bullish - In Range (50-60)
            if (50 <= m15_rsi <= 60) and (50 <= h1_rsi <= 60) and (50 <= h4_rsi <= 60):
                classification = 'bullish_in_range'
            # Bullish - Range Break (60-70)
            elif (60 <= m15_rsi <= 70) and (60 <= h1_rsi <= 70) and (h4_rsi < 65):
                classification = 'bullish_range_break'
            else:
                return None
        
        # Check for bearish conditions
        elif m15_trend == h1_trend == 'bearish':
            # Bearish - In Range (40-50)
            if (40 <= m15_rsi <= 50) and (40 <= h1_rsi <= 50) and (40 <= h4_rsi <= 50):
                classification = 'bearish_in_range'
            # Bearish - Range Break (30-40)
            elif (30 <= m15_rsi <= 40) and (30 <= h1_rsi <= 40) and (h4_rsi > 45):
                classification = 'bearish_range_break'
            else:
                return None
        else:
            return None
        
        # Update progress
        progress = (current_index + 1) / total_symbols
        st.session_state.current_progress = progress
        st.session_state.current_symbol = symbol
        progress_bar.progress(progress)
        status_text.text(f"🔍 Scanning {symbol} ({current_index+1}/{total_symbols})")
        
        return symbol, classification
    
    except Exception as e:
        st.error(f"Error classifying {symbol}: {str(e)}")
        return None

async def run_scanner_async():
    # Initialize live display containers
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Create columns for live results
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.subheader("🐂 Bullish - In Range")
        live_bullish_in_range = st.empty()
    with col2:
        st.subheader("🚀 Bullish - Break")
        live_bullish_break = st.empty()
    with col3:
        st.subheader("🐻 Bearish - In Range")
        live_bearish_in_range = st.empty()
    with col4:
        st.subheader("💥 Bearish - Break")
        live_bearish_break = st.empty()

    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession(connector=connector) as session:
        symbols = await get_futures_symbols(session)
        total_symbols = len(symbols)
        
        # Process symbols in batches to update UI more frequently
        batch_size = 5
        for i in range(0, total_symbols, batch_size):
            batch = symbols[i:i + batch_size]
            tasks = [classify_token(session, sym, progress_bar, status_text, total_symbols, i + idx) 
                    for idx, sym in enumerate(batch)]
            
            for task in asyncio.as_completed(tasks):
                result = await task
                if result:
                    symbol, classification = result
                    st.session_state.scan_results['live_results'][classification].append(symbol)
                    st.session_state.scan_results[classification].append(symbol)
                    
                    # Update live displays
                    live_bullish_in_range.write(st.session_state.scan_results['live_results']['bullish_in_range'] or "None")
                    live_bullish_break.write(st.session_state.scan_results['live_results']['bullish_range_break'] or "None")
                    live_bearish_in_range.write(st.session_state.scan_results['live_results']['bearish_in_range'] or "None")
                    live_bearish_break.write(st.session_state.scan_results['live_results']['bearish_range_break'] or "None")

    # Finalize results
    st.session_state.scan_results['scan_time'] = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    progress_bar.empty()
    status_text.success("✅ Scan completed!")

def run_scanner():
    asyncio.run(run_scanner_async())

# === STREAMLIT APP ===
st.set_page_config(page_title="Binance Trend Scanner", layout="wide")
st.title("📈 Binance Futures Trend Scanner")

st.markdown("""
Scan for trending Binance USDT Perpetual tokens using:
- 21/55/100 EMAs on 15m
- 7/30/100 SMAs on 1h & 4h
- RSI filters for precise entry points
""")

if st.button("🚀 Run Trend Scan Now"):
    # Reset live results
    st.session_state.scan_results['live_results'] = {
        'bullish_in_range': [],
        'bullish_range_break': [],
        'bearish_in_range': [],
        'bearish_range_break': []
    }
    run_scanner()

# Display only live results with download buttons
if st.session_state.scan_results['scan_time']:
    # Create 4 columns for the live results display
    col1, col2, col3, col4 = st.columns(4)
    
    timestamp = st.session_state.scan_results['scan_time']
    
    with col1:
        st.subheader("🐂 Bullish - In Range")
        bull_range = st.session_state.scan_results['bullish_in_range']
        st.write([f"{s}.P" for s in bull_range] or "None")
        
        # Download buttons with unique keys
        if bull_range:
            st.download_button(
                label="📋 TXT Export",
                data="\n".join([f"BINANCE:{s}.P" for s in sorted(bull_range)]),
                file_name=f"kaiju_bullrange_bfuscan_{timestamp}.txt",
                mime="text/plain",
                key=f"bull_range_txt_{timestamp}"
            )
            st.download_button(
                label="📁 CSV Export",
                data=pd.DataFrame({
                    "Symbol": [f"{s}.P" for s in bull_range],
                    "Category": ["Bullish - In Range"] * len(bull_range)
                }).to_csv(index=False).encode('utf-8'),
                file_name=f"kaiju_bullrange_bfuscan_{timestamp}.csv",
                mime="text/csv",
                key=f"bull_range_csv_{timestamp}"
            )
        else:
            st.button("📋 TXT Export (No Data)", 
                     disabled=True,
                     key=f"bull_range_txt_disabled_{timestamp}")
            st.button("📁 CSV Export (No Data)", 
                     disabled=True,
                     key=f"bull_range_csv_disabled_{timestamp}")

    with col2:
        st.subheader("🚀 Bullish - Break")
        bull_break = st.session_state.scan_results['bullish_range_break']
        st.write([f"{s}.P" for s in bull_break] or "None")
        
        if bull_break:
            st.download_button(
                label="📋 TXT Export",
                data="\n".join([f"BINANCE:{s}.P" for s in sorted(bull_break)]),
                file_name=f"kaiju_bullbreak_bfuscan_{timestamp}.txt",
                mime="text/plain",
                key=f"bull_break_txt_{timestamp}"
            )
            st.download_button(
                label="📁 CSV Export",
                data=pd.DataFrame({
                    "Symbol": [f"{s}.P" for s in bull_break],
                    "Category": ["Bullish - Range Break"] * len(bull_break)
                }).to_csv(index=False).encode('utf-8'),
                file_name=f"kaiju_bullbreak_bfuscan_{timestamp}.csv",
                mime="text/csv",
                key=f"bull_break_csv_{timestamp}"
            )
        else:
            st.button("📋 TXT Export (No Data)", 
                     disabled=True,
                     key=f"bull_break_txt_disabled_{timestamp}")
            st.button("📁 CSV Export (No Data)", 
                     disabled=True,
                     key=f"bull_break_csv_disabled_{timestamp}")

    with col3:
        st.subheader("🐻 Bearish - In Range")
        bear_range = st.session_state.scan_results['bearish_in_range']
        st.write([f"{s}.P" for s in bear_range] or "None")
        
        if bear_range:
            st.download_button(
                label="📋 TXT Export",
                data="\n".join([f"BINANCE:{s}.P" for s in sorted(bear_range)]),
                file_name=f"kaiju_bearrange_bfuscan_{timestamp}.txt",
                mime="text/plain",
                key=f"bear_range_txt_{timestamp}"
            )
            st.download_button(
                label="📁 CSV Export",
                data=pd.DataFrame({
                    "Symbol": [f"{s}.P" for s in bear_range],
                    "Category": ["Bearish - In Range"] * len(bear_range)
                }).to_csv(index=False).encode('utf-8'),
                file_name=f"kaiju_bearrange_bfuscan_{timestamp}.csv",
                mime="text/csv",
                key=f"bear_range_csv_{timestamp}"
            )
        else:
            st.button("📋 TXT Export (No Data)", 
                     disabled=True,
                     key=f"bear_range_txt_disabled_{timestamp}")
            st.button("📁 CSV Export (No Data)", 
                     disabled=True,
                     key=f"bear_range_csv_disabled_{timestamp}")

    with col4:
        st.subheader("💥 Bearish - Break")
        bear_break = st.session_state.scan_results['bearish_range_break']
        st.write([f"{s}.P" for s in bear_break] or "None")
        
        if bear_break:
            st.download_button(
                label="📋 TXT Export",
                data="\n".join([f"BINANCE:{s}.P" for s in sorted(bear_break)]),
                file_name=f"kaiju_bearbreak_bfuscan_{timestamp}.txt",
                mime="text/plain",
                key=f"bear_break_txt_{timestamp}"
            )
            st.download_button(
                label="📁 CSV Export",
                data=pd.DataFrame({
                    "Symbol": [f"{s}.P" for s in bear_break],
                    "Category": ["Bearish - Range Break"] * len(bear_break)
                }).to_csv(index=False).encode('utf-8'),
                file_name=f"kaiju_bearbreak_bfuscan_{timestamp}.csv",
                mime="text/csv",
                key=f"bear_break_csv_{timestamp}"
            )
        else:
            st.button("📋 TXT Export (No Data)", 
                     disabled=True,
                     key=f"bear_break_txt_disabled_{timestamp}")
            st.button("📁 CSV Export (No Data)", 
                     disabled=True,
                     key=f"bear_break_csv_disabled_{timestamp}")