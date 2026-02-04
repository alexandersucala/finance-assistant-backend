# backend/config.py

# Top 100 Most Popular Stocks (S&P 100 + Popular Growth/Tech Stocks)
SUPPORTED_TICKERS = [
    # Mega Cap Tech (FAANG+)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    
    # Major Tech & Software
    "ORCL", "CSCO", "ADBE", "CRM", "INTC", "AMD", "QCOM", "TXN", "AVGO", "NFLX",
    "SPOT", "UBER", "LYFT", "SNAP", "PINS", "SQ", "PYPL", "ABNB", "COIN", "RBLX",
    
    # Cloud & AI
    "NOW", "SNOW", "PLTR", "AI", "DDOG", "CRWD", "ZS", "NET", "MDB", "TEAM",
    
    # Finance & Fintech
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP", "BLK", "SCHW",
    
    # Healthcare & Pharma
    "JNJ", "UNH", "PFE", "ABBV", "TMO", "MRK", "ABT", "LLY", "DHR", "BMY",
    
    # Consumer & Retail
    "WMT", "HD", "MCD", "NKE", "SBUX", "TGT", "COST", "LOW", "DIS", "CMCSA",
    
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    
    # Industrials & Manufacturing
    "BA", "CAT", "GE", "HON", "UPS", "MMM", "DE", "LMT", "RTX",
    
    # Auto & EV
    "F", "GM", "RIVN", "LCID", "NIO",
    
    # Telecom
    "T", "VZ", "TMUS",
    
    # Semiconductors
    "TSM", "ASML", "MU", "AMAT", "LRCX", "KLAC", "ADI"
]

def is_ticker_supported(ticker: str) -> bool:
    """Check if we support this ticker"""
    return ticker.upper() in SUPPORTED_TICKERS


def get_supported_count() -> int:
    """Get count of supported tickers"""
    return len(SUPPORTED_TICKERS)
