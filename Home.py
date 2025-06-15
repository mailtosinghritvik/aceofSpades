import streamlit as st
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import warnings
import os
import json
from datetime import timezone
import time
from functools import lru_cache
import requests

# Suppress warnings from yfinance
warnings.filterwarnings("ignore")

# Set page configuration
st.set_page_config(
    page_title="Financial Dashboard",
    page_icon="📊",
    layout="wide"
)

# Load Supabase credentials
try:
    with open('.streamlit/secrets.toml') as f:
        config = json.load(f)
        supabase_url = config.get('SUPABASE_URL')
        supabase_key = config.get('SUPABASE_KEY')
except:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]

# Initialize Supabase client
supabase = create_client(supabase_url, supabase_key)

@st.cache_data(ttl=60)  # Cache data for 1 minute
def get_stock_data(symbol):
    """Fetch stock data using yfinance with rate limiting"""
    try:
        # Rate limiting: ensure at least 2 seconds between requests for the same symbol
        current_time = time.time()
        if symbol in st.session_state.last_request_time:
            time_since_last_request = current_time - st.session_state.last_request_time[symbol]
            if time_since_last_request < 2:
                time.sleep(2 - time_since_last_request)
        
        st.session_state.last_request_time[symbol] = current_time
        
        # Create Ticker object with custom headers
        stock = yf.Ticker(symbol, session=requests.Session().headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }))
        
        info = stock.info
        current_price = info.get('regularMarketPrice', 0)
        previous_close = info.get('regularMarketPreviousClose', 0)
        company_name = info.get('longName', symbol)
        
        if current_price and previous_close:
            percent_change = ((current_price - previous_close) / previous_close) * 100
        else:
            percent_change = 0
            
        business_summary = info.get('longBusinessSummary', "No summary available")
        return {
            'symbol': symbol,
            'name': company_name,
            'price': current_price,
            'change': percent_change,
            'summary': business_summary
        }
    except Exception as e:
        st.error(f"Error fetching data for {symbol}: {str(e)}")
        return None

# Initialize session state for rate limiting
if 'last_request_time' not in st.session_state:
    st.session_state.last_request_time = {}

# Page Header
st.title("Financial Dashboard")
st.caption("Real-time stock analysis and AI-powered insights")

# Search Bar
search = st.text_input("Search stocks...", placeholder="Enter stock symbol (e.g., AAPL)")

# Recently Viewed Section
st.header("Recently Viewed")

# Get records from Supabase
response = supabase.table('tickers').select("*").execute()
records = response.data

# Filter recent records (within last 3 minutes)
recent_threshold = datetime.now(timezone.utc) - timedelta(minutes=3)
recent_records = []
other_records = []

for record in records:
    # Parse the ISO format datetime string and ensure it's UTC
    last_accessed = datetime.fromisoformat(record['last_accessed'].replace('Z', '+00:00'))
    if last_accessed > recent_threshold:
        recent_records.append(record)
    else:
        other_records.append(record)

# Function to display stock card
def display_stock_card(stock_data):
    if stock_data:
        st.subheader(f"{stock_data['symbol']}")
        st.text(stock_data['name'])
        price = f"${stock_data['price']:.2f}"
        change = f"{stock_data['change']:+.2f}%"
        
        col1, col2 = st.columns(2)
        col1.metric("Price", price)
        
        if stock_data['change'] > 0:
            col2.markdown(f"<p style='color: green;'>{change}</p>", unsafe_allow_html=True)
        else:
            col2.markdown(f"<p style='color: red;'>{change}</p>", unsafe_allow_html=True)
        
        with st.expander("Business Summary"):
            st.write(stock_data['summary'])

# Display recent records in a grid
if recent_records:
    cols = st.columns(3)
    for idx, record in enumerate(recent_records):
        with cols[idx % 3]:
            stock_data = get_stock_data(record['ticker'])
            if stock_data:
                with st.container():
                    display_stock_card(stock_data)
else:
    st.info("No recently viewed stocks")

# Market Overview Section
if other_records:
    st.header("Market Overview")
    market_cols = st.columns(3)
    for idx, record in enumerate(other_records):
        with market_cols[idx % 3]:
            stock_data = get_stock_data(record['ticker'])
            if stock_data:
                with st.container():
                    display_stock_card(stock_data)