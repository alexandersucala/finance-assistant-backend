# backend/database.py

import sqlite3
from datetime import datetime, timedelta
import json
import os
from pathlib import Path

# Database file path
DB_PATH = Path(__file__).parent.parent / "cache.db"

# Freshness rules for different data types
FRESHNESS = {
    'realtime': timedelta(minutes=15),      # 15 min during market hours
    'daily': timedelta(days=1),             # 24 hours
    'weekly': timedelta(days=7),            # 7 days
    'monthly': timedelta(days=30),          # 30 days
    'articles': timedelta(days=7),          # 7 days
    'historical': timedelta(days=365*10)    # Basically never expire (10 years)
}


def init_database():
    """Initialize the cache database and create tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            ticker TEXT NOT NULL,
            data_type TEXT NOT NULL,
            data TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            PRIMARY KEY (ticker, data_type)
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"✓ Database initialized: {DB_PATH}")

def track_usage(identifier: str) -> Dict[str, Any]:
    """
    Track usage by IP or user ID.
    Returns: {count: int, limit_hit: bool, reset_date: str}
    """
    conn = _get_db()
    cursor = conn.cursor()
    
    # Create usage table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_tracking (
            identifier TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            first_used TEXT,
            last_used TEXT,
            is_paid BOOLEAN DEFAULT 0
        )
    ''')
    
    # Get current usage
    cursor.execute(
        'SELECT count, is_paid FROM usage_tracking WHERE identifier = ?',
        (identifier,)
    )
    row = cursor.fetchone()
    
    if row:
        count, is_paid = row
        # Increment count
        cursor.execute(
            '''UPDATE usage_tracking 
               SET count = count + 1, last_used = ? 
               WHERE identifier = ?''',
            (datetime.now().isoformat(), identifier)
        )
        count += 1
    else:
        # First use
        cursor.execute(
            '''INSERT INTO usage_tracking 
               (identifier, count, first_used, last_used, is_paid) 
               VALUES (?, 1, ?, ?, 0)''',
            (identifier, datetime.now().isoformat(), datetime.now().isoformat())
        )
        count = 1
        is_paid = False
    
    conn.commit()
    
    FREE_LIMIT = 5
    limit_hit = count > FREE_LIMIT and not is_paid
    
    return {
        "count": count,
        "limit_hit": limit_hit,
        "is_paid": bool(is_paid),
        "remaining": max(0, FREE_LIMIT - count) if not is_paid else -1
    }

def mark_user_as_paid(identifier: str) -> bool:
    """Mark a user as having paid subscription"""
    conn = _get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        'UPDATE usage_tracking SET is_paid = 1 WHERE identifier = ?',
        (identifier,)
    )
    
    # If user doesn't exist yet, create them as paid
    if cursor.rowcount == 0:
        cursor.execute(
            '''INSERT INTO usage_tracking 
               (identifier, count, first_used, last_used, is_paid) 
               VALUES (?, 0, ?, ?, 1)''',
            (identifier, datetime.now().isoformat(), datetime.now().isoformat())
        )
    
    conn.commit()
    print(f"✓ Marked {identifier} as paid user")
    return True

def get_cached_data(ticker: str, data_type: str) -> dict:
    """
    Get cached data if still fresh.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'TSLA')
        data_type: One of: 'realtime', 'daily', 'weekly', 'monthly', 'historical', 'articles'
        
    Returns:
        Cached data dict if fresh, None if stale or not found
    """
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT data, timestamp FROM cache 
            WHERE ticker = ? AND data_type = ?
        """, (ticker.upper(), data_type))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        data, timestamp = row
        cached_time = datetime.fromisoformat(timestamp)
        age = datetime.now() - cached_time
        
        # Check if still fresh
        if age < FRESHNESS.get(data_type, timedelta(days=1)):
            return json.loads(data)
        
        return None  # Stale, need to refetch
        
    except Exception as e:
        print(f"⚠ Cache read error: {e}")
        return None


def cache_data(ticker: str, data_type: str, data: dict):
    """
    Store data with timestamp in cache.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'TSLA')
        data_type: One of: 'realtime', 'daily', 'weekly', 'monthly', 'historical', 'articles'
        data: Dictionary to cache
    """
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO cache (ticker, data_type, data, timestamp)
            VALUES (?, ?, ?, ?)
        """, (ticker.upper(), data_type, json.dumps(data), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"⚠ Cache write error: {e}")


def clear_cache(ticker: str = None, data_type: str = None):
    """
    Clear cache entries. If no parameters provided, clears entire cache.
    
    Args:
        ticker: Optional - clear only this ticker
        data_type: Optional - clear only this data type
    """
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if ticker and data_type:
            cursor.execute("DELETE FROM cache WHERE ticker = ? AND data_type = ?", 
                         (ticker.upper(), data_type))
            print(f"✓ Cleared cache: {ticker} - {data_type}")
        elif ticker:
            cursor.execute("DELETE FROM cache WHERE ticker = ?", (ticker.upper(),))
            print(f"✓ Cleared all cache for: {ticker}")
        elif data_type:
            cursor.execute("DELETE FROM cache WHERE data_type = ?", (data_type,))
            print(f"✓ Cleared all {data_type} cache")
        else:
            cursor.execute("DELETE FROM cache")
            print("✓ Cleared entire cache")
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"⚠ Cache clear error: {e}")


def get_cache_stats():
    """Get statistics about cached data"""
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM cache")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT ticker, COUNT(*) FROM cache GROUP BY ticker")
        by_ticker = cursor.fetchall()
        
        cursor.execute("SELECT data_type, COUNT(*) FROM cache GROUP BY data_type")
        by_type = cursor.fetchall()
        
        conn.close()
        
        return {
            "total_entries": total,
            "by_ticker": dict(by_ticker),
            "by_type": dict(by_type)
        }
        
    except Exception as e:
        print(f"⚠ Cache stats error: {e}")
        return None


if __name__ == "__main__":
    """Test database functions"""
    print("\n" + "="*60)
    print("DATABASE MODULE - Test")
    print("="*60)
    
    # Initialize
    init_database()
    
    # Test cache write
    print("\nTesting cache write...")
    test_data = {"price": 250.50, "volume": 1000000}
    cache_data("TSLA", "realtime", test_data)
    print("✓ Wrote test data")
    
    # Test cache read
    print("\nTesting cache read...")
    cached = get_cached_data("TSLA", "realtime")
    if cached:
        print(f"✓ Read cached data: {cached}")
    else:
        print("✗ No cached data found")
    
    # Test stats
    print("\nCache statistics:")
    stats = get_cache_stats()
    if stats:
        print(f"Total entries: {stats['total_entries']}")
        print(f"By ticker: {stats['by_ticker']}")
        print(f"By type: {stats['by_type']}")
    
    print("\n" + "="*60)
