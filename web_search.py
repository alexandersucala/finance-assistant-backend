# backend/web_search.py

import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv
import sys
from pathlib import Path

# Load environment
load_dotenv()

# Import database for caching
sys.path.append(str(Path(__file__).parent))
from database import get_cached_data, cache_data

# Trusted financial sources (expanded list)
TRUSTED_DOMAINS = [
    "seekingalpha.com",
    "bloomberg.com",
    "reuters.com",
    "wsj.com",
    "ft.com",
    "marketwatch.com",
    "cnbc.com",
    "barrons.com",
    "fool.com",
    "morningstar.com",
    "benzinga.com",
    "investors.com"
]


def search_stock_articles(ticker: str, days_back: int = 7, max_results: int = 5) -> List[Dict]:
    """
    Search for recent stock analysis articles from trusted sources.
    Uses caching to save API calls.
    
    Args:
        ticker: Stock symbol (e.g., 'TSLA')
        days_back: How many days back to search
        max_results: Maximum number of articles to return
        
    Returns:
        List of article dictionaries with title, source, url, date
    """
    
    ticker = ticker.upper()
    cache_key = f"articles_{days_back}days"
    
    # Check cache (7 day freshness for articles)
    cached = get_cached_data(ticker, cache_key)
    if cached:
        print(f"✓ Cache hit: {ticker} articles")
        return cached.get('articles', [])
    
    print(f"⏳ Searching for {ticker} articles (last {days_back} days)...")
    
    # Try real search first, fall back to mock if unavailable
    brave_api_key = os.getenv("BRAVE_API_KEY")
    
    if brave_api_key and brave_api_key != "your_key_here":
        articles = _brave_search(ticker, days_back, max_results, brave_api_key)
    else:
        print("⚠ BRAVE_API_KEY not configured, using mock data")
        articles = _mock_article_search(ticker, days_back, max_results)
    
    # Cache the results
    cache_data(ticker, cache_key, {"articles": articles, "count": len(articles)})
    
    print(f"✓ Found {len(articles)} articles for {ticker}")
    return articles


def _brave_search(ticker: str, days_back: int, max_results: int, api_key: str) -> List[Dict]:
    """
    Real Brave Search API implementation.
    Searches trusted financial domains for stock analysis.
    """
    
    import requests
    from urllib.parse import quote
    
    # Build search query targeting trusted domains
    # Use OR to search multiple domains
    domain_query = " OR ".join([f"site:{domain}" for domain in TRUSTED_DOMAINS[:5]])  # Limit to top 5 to keep query reasonable
    search_query = f"({domain_query}) {ticker} stock analysis"
    
    # Brave Search API endpoint
    url = "https://api.search.brave.com/res/v1/web/search"
    
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    
    params = {
        "q": search_query,
        "count": max_results,
        "freshness": f"pw" if days_back <= 7 else f"pm"  # pw = past week, pm = past month
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        articles = []
        web_results = data.get('web', {}).get('results', [])
        
        for result in web_results[:max_results]:
            # Extract domain from URL
            url_str = result.get('url', '')
            domain = None
            for trusted_domain in TRUSTED_DOMAINS:
                if trusted_domain in url_str:
                    domain = trusted_domain
                    break
            
            if not domain:
                continue  # Skip non-trusted sources
            
            # Get source name from domain
            source_map = {
                "seekingalpha.com": "Seeking Alpha",
                "bloomberg.com": "Bloomberg",
                "reuters.com": "Reuters",
                "wsj.com": "Wall Street Journal",
                "ft.com": "Financial Times",
                "marketwatch.com": "MarketWatch",
                "cnbc.com": "CNBC",
                "barrons.com": "Barron's",
                "fool.com": "The Motley Fool",
                "morningstar.com": "Morningstar",
                "benzinga.com": "Benzinga",
                "investors.com": "Investor's Business Daily"
            }
            
            articles.append({
                "title": result.get('title', 'Untitled'),
                "source": source_map.get(domain, domain),
                "domain": domain,
                "url": url_str,
                "date": result.get('age', 'Recent'),  # Brave returns relative dates
                "snippet": result.get('description', ''),
                "is_trusted": True
            })
        
        print(f"✓ Brave Search returned {len(articles)} trusted articles")
        return articles
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print("⚠ Brave API rate limit hit, using mock data")
        else:
            print(f"⚠ Brave API error: {e}, using mock data")
        return _mock_article_search(ticker, days_back, max_results)
    except Exception as e:
        print(f"⚠ Search failed: {e}, using mock data")
        return _mock_article_search(ticker, days_back, max_results)


def _mock_article_search(ticker: str, days_back: int, max_results: int) -> List[Dict]:
    """
    Mock article search for MVP testing.
    In production, replace with real Brave/Google Search API.
    
    Returns realistic-looking article data for testing.
    """
    
    # Generate mock articles based on ticker
    base_date = datetime.now()
    
    mock_articles = []
    
    # Different article types based on common stock scenarios
    article_templates = [
        {
            "title": f"{ticker} Stock Analysis: Key Factors Driving Recent Performance",
            "source": "Seeking Alpha",
            "domain": "seekingalpha.com",
            "days_ago": 1
        },
        {
            "title": f"Why {ticker} Shares Are Moving Today",
            "source": "The Motley Fool",
            "domain": "fool.com",
            "days_ago": 2
        },
        {
            "title": f"{ticker} Q4 Earnings: What Wall Street Expects",
            "source": "MarketWatch",
            "domain": "marketwatch.com",
            "days_ago": 3
        },
        {
            "title": f"Analyst Upgrades {ticker} on Strong Fundamentals",
            "source": "Barron's",
            "domain": "barrons.com",
            "days_ago": 5
        },
        {
            "title": f"{ticker} Investment Thesis: Bull vs Bear Case",
            "source": "Bloomberg",
            "domain": "bloomberg.com",
            "days_ago": 6
        }
    ]
    
    for template in article_templates[:max_results]:
        if template["days_ago"] <= days_back:
            article_date = base_date - timedelta(days=template["days_ago"])
            mock_articles.append({
                "title": template["title"],
                "source": template["source"],
                "domain": template["domain"],
                "url": f"https://{template['domain']}/article/{ticker.lower()}-analysis",
                "date": article_date.strftime("%Y-%m-%d"),
                "snippet": f"Recent analysis of {ticker} covering market trends, fundamental analysis, and price targets.",
                "is_trusted": True
            })
    
    return mock_articles


def get_article_summary(ticker: str, articles: List[Dict]) -> Dict:
    """
    Summarize article search results for confidence calculation.
    
    Args:
        ticker: Stock symbol
        articles: List of article dictionaries
        
    Returns:
        Summary dict with count, recency, source quality
    """
    
    if not articles:
        return {
            "count": 0,
            "has_recent": False,
            "trusted_sources": 0,
            "newest_date": None,
            "sources": []
        }
    
    # Calculate metrics
    trusted_count = sum(1 for a in articles if a.get('is_trusted', False))
    sources = list(set(a.get('source', 'Unknown') for a in articles))
    
    # Check recency (within 3 days = "recent")
    newest = articles[0] if articles else None
    has_recent = False
    
    if newest and newest.get('date'):
        try:
            article_date = datetime.strptime(newest['date'], "%Y-%m-%d")
            days_old = (datetime.now() - article_date).days
            has_recent = days_old <= 3
        except:
            pass
    
    return {
        "count": len(articles),
        "has_recent": has_recent,
        "trusted_sources": trusted_count,
        "newest_date": newest.get('date') if newest else None,
        "sources": sources
    }


def search_with_real_api(ticker: str, api_key: str = None) -> List[Dict]:
    """
    Placeholder for real search API integration.
    
    To implement:
    1. Sign up for Brave Search API or Google Custom Search
    2. Use site: operator to restrict to trusted domains
    3. Parse results and return structured data
    
    Example Brave Search query:
    query = f"site:seekingalpha.com OR site:bloomberg.com {ticker} stock analysis"
    """
    
    # TODO: Implement real API call when ready
    # For now, falls back to mock
    print("⚠ Real search API not configured, using mock data")
    return _mock_article_search(ticker, 7, 5)


if __name__ == "__main__":
    """Test web search functions"""
    print("\n" + "="*60)
    print("WEB SEARCH MODULE - Test")
    print("="*60)
    
    ticker = "TSLA"
    
    print(f"\n[TEST 1] Searching for {ticker} articles...")
    articles = search_stock_articles(ticker, days_back=7, max_results=5)
    
    if articles:
        print(f"\n✓ Found {len(articles)} articles:")
        for i, article in enumerate(articles, 1):
            print(f"\n  [{i}] {article['title']}")
            print(f"      Source: {article['source']} ({article['date']})")
            print(f"      URL: {article['url']}")
    
    print(f"\n[TEST 2] Getting article summary...")
    summary = get_article_summary(ticker, articles)
    print(f"✓ Article Summary:")
    print(f"  Total articles: {summary['count']}")
    print(f"  Has recent (≤3 days): {summary['has_recent']}")
    print(f"  Trusted sources: {summary['trusted_sources']}")
    print(f"  Sources: {', '.join(summary['sources'])}")
    
    print(f"\n[TEST 3] Search again (should hit cache)...")
    articles2 = search_stock_articles(ticker, days_back=7, max_results=5)
    
    print("\n" + "="*60)
    print("NOTE: Currently using MOCK data for testing")
    print("To enable real search:")
    print("1. Sign up for Brave Search API (free tier)")
    print("2. Add BRAVE_API_KEY to .env")
    print("3. Implement search_with_real_api() function")
    print("="*60)
