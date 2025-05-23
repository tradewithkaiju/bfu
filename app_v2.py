import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
from threading import Thread
import ta
from ta.trend import EMAIndicator, SMAIndicator

# Initialize session state
if 'scan_data' not in st.session_state:
    st.session_state.scan_data = {
        'bullish': [],
        'bearish': [],
        'last_scan': "Not scanned yet",
        'next_scan': "Soon...",
        'is_scanning': False
    }

# === CONFIG ===
BASE_URL = "https://fapi.binance.com"
TEST_MODE = True
TEST_SYMBOLS_COUNT = 5
SCAN_INTERVAL = 300  # 5 minutes in seconds

# === MOVING AVERAGE UTILS === 
# [Keep your existing calculate_ema, calculate_sma, fully_fanned functions]

# === BINANCE API UTILS ===
# [Keep your existing get_futures_symbols, fetch_ohlcv, classify_token functions]

def run_scanner():
    st.session_state.scan_data['is_scanning'] = True
    try:
        symbols = get_futures_symbols()
        bullish, bearish = [], []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, symbol in enumerate(symbols):
            trend = classify_token(symbol)
            if trend == 'bullish': bullish.append(symbol)
            elif trend == 'bearish': bearish.append(symbol)
            
            progress = (i + 1) / len(symbols)
            progress_bar.progress(progress)
            status_text.text(f"Scanning {symbol} ({i+1}/{len(symbols)})")
            time.sleep(0.1)  # Rate limiting
            
        st.session_state.scan_data.update({
            'bullish': bullish,
            'bearish': bearish,
            'last_scan': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'next_scan': (datetime.now() + timedelta(seconds=SCAN_INTERVAL)).strftime("%H:%M"),
            'is_scanning': False
        })
        
        progress_bar.empty()
        status_text.empty()
        
    except Exception as e:
        st.error(f"Scan failed: {e}")
        st.session_state.scan_data['is_scanning'] = False

# === STREAMLIT UI ===
st.set_page_config(page_title="Binance Trend Scanner", layout="wide")
st.title("📈 Binance Futures Trend Scanner")

# Status panel
cols = st.columns(3)
cols[0].metric("Last Scan", st.session_state.scan_data['last_scan'])
cols[1].metric("Next Scan", st.session_state.scan_data['next_scan'])
cols[2].metric("Status", "🔄 Scanning..." if st.session_state.scan_data['is_scanning'] else "✅ Ready")

# Manual refresh button
if st.button("🔁 Manual Refresh", disabled=st.session_state.scan_data['is_scanning']):
    Thread(target=run_scanner, daemon=True).start()

# Results display
tab1, tab2 = st.tabs(["📈 Bullish", "📉 Bearish"])
with tab1:
    st.write([f"{s}.P" for s in st.session_state.scan_data['bullish']] or "No bullish tokens")
with tab2:
    st.write([f"{s}.P" for s in st.session_state.scan_data['bearish']] or "No bearish tokens")

# Download button
st.download_button(
    label="📥 Download Watchlist",
    data="\n".join([f"BINANCE:{s}.P" for s in st.session_state.scan_data['bullish'] + st.session_state.scan_data['bearish']]),
    file_name=f"binance_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
    disabled=st.session_state.scan_data['is_scanning']
)

# Auto-scan thread (runs in background)
if 'scanner_thread' not in st.session_state:
    def auto_scanner():
        while True:
            if not st.session_state.scan_data['is_scanning']:
                run_scanner()
            time.sleep(SCAN_INTERVAL)
    
    st.session_state.scanner_thread = Thread(target=auto_scanner, daemon=True)
    st.session_state.scanner_thread.start()