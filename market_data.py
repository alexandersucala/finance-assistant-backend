# backend/market_data.py
# Alpha Vantage Premium Tier ($50/month) - 15-minute delayed intraday data

import requests
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
from dotenv import load_dotenv
import sys
from pathlib import Path
import time

# Load environment variables
load_dotenv()

# Import database functions
sys.path.append(str(Path(__file__).parent))
from database import get_cached_data, cache_data

# Alpha Vantage API Key
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"


def get_current_price(ticker: str) -> Optional[Dict]:
    """
    Get current stock price from Alpha Vantage using 1-minute intraday data.
    Premium tier provides 15-minute delayed data during market hours.
    Uses 2-minute cache to stay fresh.
    
    Args:
        ticker: Stock symbol (e.g., 'TSLA')
        
    Returns:
        Dictionary with current price data or None if failed
    """
    
    ticker = ticker.upper()
    
    # Check cache first (2 minute cache)
    cached = get_cached_data(ticker, 'realtime')
    if cached:
        cache_age = (datetime.now() - datetime.fromisoformat(cached['timestamp'])).total_seconds()
        if cache_age < 120:  # 2 minutes
            data_age_str = cached.get('data_age_display', 'unknown age')
            print(f"✓ Cache hit: {ticker} realtime data (cache: {int(cache_age)}s old, market data: {data_age_str})")
            return cached
    
    print(f"⏳ Fetching {ticker} current price from Alpha Vantage (Premium 1min intraday)...")
    
    try:
        # Use TIME_SERIES_INTRADAY with 1min interval for freshest premium data
        params = {
            'function': 'TIME_SERIES_INTRADAY',
            'symbol': ticker,
            'interval': '1min',
            'outputsize': 'compact',  # Latest 100 data points
            'entitlement': 'delayed',  # CRITICAL: Required for 15-min    delayed premium data
            'apikey': ALPHA_VANTAGE_API_KEY
         }
        
        response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        data_json = response.json()
        
        # Check for rate limit or error
        if 'Note' in data_json:
            print(f"⚠ Rate limit hit: {data_json['Note']}")
            return None
        
        if 'Error Message' in data_json:
            print(f"✗ API Error: {data_json['Error Message']}")
            return None
        
        if 'Information' in data_json:
            print(f"⚠ API Info: {data_json['Information']}")
            return None
        
        if 'Time Series (1min)' not in data_json:
            print(f"✗ No intraday data returned for {ticker}")
            print(f"Response keys: {list(data_json.keys())}")
            return None
        
        time_series = data_json['Time Series (1min)']
        
        if not time_series:
            print(f"✗ Empty time series for {ticker}")
            return None
        
        # Get the most recent data point (first key when sorted)
        latest_timestamp = sorted(time_series.keys(), reverse=True)[0]
        latest_data = time_series[latest_timestamp]
        
        # Calculate how old the data is
        try:
            data_time = datetime.fromisoformat(latest_timestamp.replace(' ', 'T'))
            data_age_seconds = (datetime.now() - data_time).total_seconds()
            data_age_minutes = int(data_age_seconds / 60)
            
            if data_age_minutes < 60:
                data_age_display = f"{data_age_minutes}min old"
            else:
                data_age_hours = int(data_age_minutes / 60)
                data_age_display = f"{data_age_hours}h {data_age_minutes % 60}min old"
        except:
            data_age_display = "unknown age"
            data_age_minutes = 999
        
        # Get previous close for change calculation
        timestamps = sorted(time_series.keys(), reverse=True)
        if len(timestamps) > 1:
            previous_data = time_series[timestamps[1]]
            previous_close = float(previous_data['4. close'])
        else:
            previous_close = float(latest_data['1. open'])
        
        current_price = float(latest_data['4. close'])
        change = current_price - previous_close
        change_percent = (change / previous_close * 100) if previous_close else 0
        
        data = {
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "previous_close": round(previous_close, 2),
            "open": round(float(latest_data['1. open']), 2),
            "day_high": round(float(latest_data['2. high']), 2),
            "day_low": round(float(latest_data['3. low']), 2),
            "volume": int(latest_data['5. volume']),
            "company_name": ticker,
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "timestamp": datetime.now().isoformat(),
            "data_timestamp": latest_timestamp,
            "data_age_minutes": data_age_minutes,
            "data_age_display": data_age_display
        }
        
        # Cache for 2 minutes
        cache_data(ticker, 'realtime', data)
        
        print(f"✓ Fetched and cached: {ticker} @ ${data['current_price']} (market data is {data_age_display})")
        
        # Warning if data is older than expected
        if data_age_minutes > 30:
            print(f"⚠ WARNING: Market data is {data_age_display} - may be stale (market closed or API delay)")
        
        return data
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Network error fetching {ticker}: {e}")
        return None
    except Exception as e:
        print(f"✗ Failed to fetch {ticker}: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_historical_data(ticker: str, period: str = "1y") -> Optional[Dict]:
    """
    Get historical stock data from Alpha Vantage.
    Cached for 1 day since historical data doesn't change much.
    """
    
    ticker = ticker.upper()
    cache_key = f"historical_{period}"
    
    # Check cache (24 hour cache)
    cached = get_cached_data(ticker, cache_key)
    if cached:
        cache_age = (datetime.now() - datetime.fromisoformat(cached['timestamp'])).total_seconds()
        if cache_age < 86400:  # 24 hours
            print(f"✓ Cache hit: {ticker} {period} historical data")
            return cached
    
    print(f"⏳ Fetching {ticker} historical data from Alpha Vantage...")
    
    try:
        params = {
            'function': 'TIME_SERIES_DAILY',
            'symbol': ticker,
            'outputsize': 'compact',
            'apikey': ALPHA_VANTAGE_API_KEY
        }
        
        response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        data_json = response.json()
        
        if 'Note' in data_json:
            print(f"⚠ Rate limit hit")
            return None
        
        if 'Error Message' in data_json:
            print(f"✗ API Error: {data_json['Error Message']}")
            return None
        
        if 'Time Series (Daily)' not in data_json:
            print(f"✗ No historical data for {ticker}")
            return None
        
        time_series = data_json['Time Series (Daily)']
        dates = sorted(time_series.keys(), reverse=True)
        
        if len(dates) < 2:
            print(f"✗ Insufficient historical data")
            return None
        
        # Filter by period
        period_days = {'1mo': 30, '3mo': 90, '6mo': 180, '1y': 365}
        days = period_days.get(period, 365)
        filtered_dates = dates[:min(days, len(dates))]
        
        # Calculate statistics
        oldest = time_series[filtered_dates[-1]]
        newest = time_series[filtered_dates[0]]
        
        opening_price = float(oldest['1. open'])
        closing_price = float(newest['4. close'])
        
        all_highs = [float(time_series[d]['2. high']) for d in filtered_dates]
        all_lows = [float(time_series[d]['3. low']) for d in filtered_dates]
        all_volumes = [int(time_series[d]['5. volume']) for d in filtered_dates]
        
        data = {
            "ticker": ticker,
            "period": period,
            "period_label": f"Past {days} days",
            "start_date": filtered_dates[-1],
            "end_date": filtered_dates[0],
            "data_points": len(filtered_dates),
            "opening_price": opening_price,
            "closing_price": closing_price,
            "high": max(all_highs),
            "low": min(all_lows),
            "avg_volume": int(sum(all_volumes) / len(all_volumes)),
            "total_return": round(((closing_price / opening_price) - 1) * 100, 2),
            "timestamp": datetime.now().isoformat()
        }
        
        cache_data(ticker, cache_key, data)
        print(f"✓ Fetched and cached: {ticker} historical ({period})")
        
        return data
        
    except Exception as e:
        print(f"✗ Failed to fetch historical data for {ticker}: {e}")
        return None


def get_company_info(ticker: str) -> Optional[Dict]:
    """
    Get company overview from Alpha Vantage.
    Cached for 30 days since it rarely changes.
    """
    
    ticker = ticker.upper()
    
    # Check cache
    cached = get_cached_data(ticker, 'company_info')
    if cached:
        print(f"✓ Cache hit: {ticker} company info")
        return cached
    
    print(f"⏳ Fetching {ticker} company info from Alpha Vantage...")
    
    try:
        params = {
            'function': 'OVERVIEW',
            'symbol': ticker,
            'apikey': ALPHA_VANTAGE_API_KEY
        }
        
        response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        overview = response.json()
        
        if 'Note' in overview:
            print(f"⚠ Rate limit hit")
            return None
        
        if not overview or 'Symbol' not in overview:
            print(f"✗ No company info for {ticker}")
            return None
        
        data = {
            "ticker": ticker,
            "company_name": overview.get('Name'),
            "sector": overview.get('Sector'),
            "industry": overview.get('Industry'),
            "description": overview.get('Description'),
            "exchange": overview.get('Exchange'),
            "market_cap": overview.get('MarketCapitalization'),
            "pe_ratio": overview.get('PERatio'),
            "dividend_yield": overview.get('DividendYield'),
            "52_week_high": overview.get('52WeekHigh'),
            "52_week_low": overview.get('52WeekLow'),
            "timestamp": datetime.now().isoformat()
        }
        
        cache_data(ticker, 'company_info', data)
        print(f"✓ Fetched and cached: {ticker} company info")
        
        return data
        
    except Exception as e:
        print(f"✗ Failed to fetch company info for {ticker}: {e}")
        return None


def get_stock_data(ticker: str, include_historical: bool = False) -> Dict:
    """
    Get comprehensive stock data (current + company info + optional historical).
    """
    
    result = {
        "ticker": ticker.upper(),
        "success": False,
        "current": None,
        "historical": None,
        "company": None,
        "errors": []
    }
    
    # Get current price (1-minute intraday, 15-min delayed)
    current = get_current_price(ticker)
    if current:
        result["current"] = current
        result["success"] = True
    else:
        result["errors"].append("Failed to fetch current price")
    
    time.sleep(0.5)
    
    # Get company info
    company = get_company_info(ticker)
    if company:
        result["company"] = company
    else:
        result["errors"].append("Failed to fetch company info")
    
    # Get historical data if requested
    if include_historical:
        time.sleep(0.5)
        historical = get_historical_data(ticker, period="1y")
        if historical:
            result["historical"] = historical
        else:
            result["errors"].append("Failed to fetch historical data")
    
    return result


if __name__ == "__main__":
    """Test market data functions"""
    print("\n" + "="*60)
    print("MARKET DATA MODULE - Test (Alpha Vantage Premium)")
    print("="*60)
    
    if not ALPHA_VANTAGE_API_KEY:
        print("✗ ERROR: ALPHA_VANTAGE_API_KEY not found in .env file")
        exit(1)
    
    print(f"✓ API Key found: {ALPHA_VANTAGE_API_KEY[:10]}...")
    print(f"✓ Premium Tier: $50/month - 15-minute delayed intraday data")
    
    # Test with TSLA
    ticker = "TSLA"
    
    print(f"\n[TEST 1] Getting current price for {ticker}...")
    current = get_current_price(ticker)
    if current:
        print(f"✓ Current price: ${current['current_price']}")
        print(f"  Market data timestamp: {current.get('data_timestamp', 'N/A')}")
        print(f"  Data age: {current.get('data_age_display', 'unknown')}")
        print(f"  Change: ${current.get('change', 'N/A')} ({current.get('change_percent', 'N/A')}%)")
        print(f"  Volume: {current.get('volume', 'N/A'):,}")
    
    print(f"\n[TEST 2] Getting full stock data...")
    stock_data = get_stock_data(ticker, include_historical=True)
    print(f"✓ Success: {stock_data['success']}")
    if stock_data['errors']:
        print(f"  Errors: {stock_data['errors']}")
    
    print("\n" + "="*60)