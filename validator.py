# backend/validator.py

from datetime import datetime, timedelta
from typing import Dict, List, Tuple


def calculate_confidence(stock_data: Dict, articles: List[Dict] = None) -> Tuple[str, int, List[str]]:
    """
    Calculate confidence level based on data quality, freshness, and article coverage.
    
    Args:
        stock_data: Dictionary from market_data.get_stock_data()
        articles: Optional list of articles from web_search
        
    Returns:
        Tuple of (level, score, missing_items):
        - level: "HIGH", "MEDIUM", or "LOW"
        - score: 0-100 confidence percentage
        - missing_items: List of what's missing/stale
    """
    
    score = 0
    missing = []
    
    # Start with base check
    if not stock_data.get('success'):
        return ("LOW", 0, ["Failed to fetch any data"])
    
    # Check current price data (30 points - reduced from 40 to make room for articles)
    current = stock_data.get('current')
    if current and current.get('current_price'):
        # Check freshness (within 1 hour)
        timestamp = current.get('timestamp')
        if timestamp:
            try:
                data_time = datetime.fromisoformat(timestamp)
                age = datetime.now() - data_time
                
                if age < timedelta(minutes=20):
                    score += 30  # Very fresh
                elif age < timedelta(hours=1):
                    score += 25  # Fresh
                elif age < timedelta(hours=24):
                    score += 18  # Same day
                    missing.append("Price data is from earlier today")
                else:
                    score += 10  # Stale
                    missing.append("Price data is over 1 day old")
            except:
                score += 20  # Has data but can't verify freshness
        else:
            score += 20  # Has price but no timestamp
    else:
        missing.append("Current price not available")
    
    # Check company info (20 points - reduced from 30)
    company = stock_data.get('company')
    if company and company.get('company_name'):
        score += 20
        
        # Bonus points for rich company data
        if company.get('description'):
            score += 3
        if company.get('sector') and company.get('industry'):
            score += 2
    else:
        missing.append("Company information not available")
    
    # Check historical data (20 points - same as before)
    historical = stock_data.get('historical')
    if historical:
        if historical.get('data_points', 0) > 20:
            score += 20
        elif historical.get('data_points', 0) > 5:
            score += 12
            missing.append("Limited historical data")
        else:
            score += 5
            missing.append("Very limited historical data")
    else:
        missing.append("Historical data not available")
    
    # NEW: Check article coverage (30 points - CRITICAL for analysis)
    if articles is not None:
        article_count = len(articles)
        
        if article_count >= 3:
            score += 30  # Excellent coverage
        elif article_count >= 2:
            score += 20  # Good coverage
            missing.append("Limited recent article coverage (only 2 articles)")
        elif article_count >= 1:
            score += 10  # Minimal coverage
            missing.append("Very limited article coverage (only 1 article)")
        else:
            missing.append("No recent articles found from trusted sources")
    else:
        # If articles weren't searched, don't penalize
        missing.append("Article search not performed")
    
    # Cap score at 100
    score = min(score, 100)
    
    # Determine level
    if score >= 80:
        level = "HIGH"
    elif score >= 50:
        level = "MEDIUM"
    else:
        level = "LOW"
    
    return (level, score, missing)
    """
    Calculate confidence level based on data quality and freshness.
    
    Args:
        stock_data: Dictionary from market_data.get_stock_data()
        
    Returns:
        Tuple of (level, score, missing_items):
        - level: "HIGH", "MEDIUM", or "LOW"
        - score: 0-100 confidence percentage
        - missing_items: List of what's missing/stale
    """
    
    score = 0
    missing = []
    
    # Start with base score
    if not stock_data.get('success'):
        return ("LOW", 0, ["Failed to fetch any data"])
    
    # Check current price data (40 points)
    current = stock_data.get('current')
    if current and current.get('current_price'):
        # Check freshness (within 1 hour)
        timestamp = current.get('timestamp')
        if timestamp:
            try:
                data_time = datetime.fromisoformat(timestamp)
                age = datetime.now() - data_time
                
                if age < timedelta(minutes=20):
                    score += 40  # Very fresh
                elif age < timedelta(hours=1):
                    score += 35  # Fresh
                elif age < timedelta(hours=24):
                    score += 25  # Same day
                    missing.append("Price data is from earlier today")
                else:
                    score += 15  # Stale
                    missing.append("Price data is over 1 day old")
            except:
                score += 30  # Has data but can't verify freshness
        else:
            score += 30  # Has price but no timestamp
    else:
        missing.append("Current price not available")
    
    # Check company info (30 points)
    company = stock_data.get('company')
    if company and company.get('company_name'):
        score += 30
        
        # Bonus points for rich company data
        if company.get('description'):
            score += 5
        if company.get('sector') and company.get('industry'):
            score += 5
    else:
        missing.append("Company information not available")
    
    # Check historical data (20 points) - if requested
    historical = stock_data.get('historical')
    if historical:
        if historical.get('data_points', 0) > 20:
            score += 20
        elif historical.get('data_points', 0) > 5:
            score += 15
            missing.append("Limited historical data")
        else:
            score += 5
            missing.append("Very limited historical data")
    # Don't penalize if historical wasn't requested
    
    # Cap score at 100
    score = min(score, 100)
    
    # Determine level
    if score >= 80:
        level = "HIGH"
    elif score >= 50:
        level = "MEDIUM"
    else:
        level = "LOW"
    
    return (level, score, missing)


def get_confidence_badge(level: str) -> Dict:
    """
    Get display properties for confidence badge.
    
    Args:
        level: "HIGH", "MEDIUM", or "LOW"
        
    Returns:
        Dictionary with color, emoji, and message
    """
    
    badges = {
        "HIGH": {
            "color": "green",
            "emoji": "🟢",
            "message": "High confidence - data is fresh and complete",
            "css_class": "confidence-high"
        },
        "MEDIUM": {
            "color": "yellow",
            "emoji": "🟡",
            "message": "Medium confidence - some data may be incomplete",
            "css_class": "confidence-medium"
        },
        "LOW": {
            "color": "red",
            "emoji": "🔴",
            "message": "Low confidence - data is missing or outdated",
            "css_class": "confidence-low"
        }
    }
    
    return badges.get(level, badges["LOW"])


def validate_stock_data(stock_data: Dict, articles: List[Dict] = None) -> Dict:
    """
    Comprehensive validation of stock data with detailed results.
    
    Args:
        stock_data: Dictionary from market_data.get_stock_data()
        articles: Optional list of articles from web_search
        
    Returns:
        Validation result dictionary with confidence, badge, and details
    """
    
    level, score, missing = calculate_confidence(stock_data, articles)
    badge = get_confidence_badge(level)
    
    # Safe get helpers
    current = stock_data.get('current') or {}
    company = stock_data.get('company') or {}
    historical = stock_data.get('historical') or {}
    
    result = {
        "valid": level in ["HIGH", "MEDIUM"],  # Only LOW is considered invalid
        "confidence_level": level,
        "confidence_score": score,
        "badge": badge,
        "missing_data": missing,
        "has_current_price": bool(current.get('current_price')),
        "has_company_info": bool(company.get('company_name')),
        "has_historical_data": bool(historical.get('data_points')),
        "has_articles": bool(articles and len(articles) > 0),
        "article_count": len(articles) if articles else 0,
        "recommendation": _get_recommendation(level, missing)
    }
    
    return result
    """
    Comprehensive validation of stock data with detailed results.
    
    Args:
        stock_data: Dictionary from market_data.get_stock_data()
        
    Returns:
        Validation result dictionary with confidence, badge, and details
    """
    
    level, score, missing = calculate_confidence(stock_data)
    badge = get_confidence_badge(level)
    
    # Safe get helpers
    current = stock_data.get('current') or {}
    company = stock_data.get('company') or {}
    historical = stock_data.get('historical') or {}
    
    result = {
        "valid": level in ["HIGH", "MEDIUM"],  # Only LOW is considered invalid
        "confidence_level": level,
        "confidence_score": score,
        "badge": badge,
        "missing_data": missing,
        "has_current_price": bool(current.get('current_price')),
        "has_company_info": bool(company.get('company_name')),
        "has_historical_data": bool(historical.get('data_points')),
        "recommendation": _get_recommendation(level, missing)
    }
    
    return result


def _get_recommendation(level: str, missing: List[str]) -> str:
    """Generate a recommendation based on confidence level"""
    
    if level == "HIGH":
        return "Data quality is excellent. Safe to provide detailed analysis."
    elif level == "MEDIUM":
        return f"Data is acceptable but incomplete. Consider mentioning: {', '.join(missing[:2])}"
    else:
        return "Data quality is too low. Recommend user try again later or check ticker symbol."


if __name__ == "__main__":
    """Test validator with mock data"""
    print("\n" + "="*60)
    print("VALIDATOR MODULE - Test")
    print("="*60)
    
    # Test Case 1: HIGH confidence (fresh, complete data)
    print("\n[TEST 1] HIGH Confidence - Fresh & Complete Data")
    high_data = {
        "ticker": "TSLA",
        "success": True,
        "current": {
            "current_price": 421.96,
            "change": 0.15,
            "change_percent": 0.0356,
            "timestamp": datetime.now().isoformat()
        },
        "company": {
            "company_name": "Tesla Inc",
            "sector": "CONSUMER CYCLICAL",
            "industry": "AUTO MANUFACTURERS",
            "description": "Tesla designs and manufactures electric vehicles..."
        },
        "historical": {
            "data_points": 30,
            "total_return": -13.55
        },
        "errors": []
    }
    
    result = validate_stock_data(high_data)
    print(f"{result['badge']['emoji']} Confidence: {result['confidence_level']} ({result['confidence_score']}%)")
    print(f"Valid: {result['valid']}")
    print(f"Missing: {result['missing_data'] if result['missing_data'] else 'None'}")
    print(f"Recommendation: {result['recommendation']}")
    
    # Test Case 2: MEDIUM confidence (missing some data)
    print("\n[TEST 2] MEDIUM Confidence - Missing Company Info")
    medium_data = {
        "ticker": "AAPL",
        "success": True,
        "current": {
            "current_price": 185.50,
            "timestamp": datetime.now().isoformat()
        },
        "company": None,
        "historical": None,
        "errors": ["Failed to fetch company info"]
    }
    
    result = validate_stock_data(medium_data)
    print(f"{result['badge']['emoji']} Confidence: {result['confidence_level']} ({result['confidence_score']}%)")
    print(f"Valid: {result['valid']}")
    print(f"Missing: {result['missing_data']}")
    print(f"Recommendation: {result['recommendation']}")
    
    # Test Case 3: LOW confidence (stale data)
    print("\n[TEST 3] LOW Confidence - Very Stale Data")
    stale_time = (datetime.now() - timedelta(days=5)).isoformat()
    low_data = {
        "ticker": "NVDA",
        "success": True,
        "current": {
            "current_price": 850.00,
            "timestamp": stale_time
        },
        "company": None,
        "historical": None,
        "errors": ["Failed to fetch company info"]
    }
    
    result = validate_stock_data(low_data)
    print(f"{result['badge']['emoji']} Confidence: {result['confidence_level']} ({result['confidence_score']}%)")
    print(f"Valid: {result['valid']}")
    print(f"Missing: {result['missing_data']}")
    print(f"Recommendation: {result['recommendation']}")
    
    # Test Case 4: FAIL - No data
    print("\n[TEST 4] FAIL - No Data Available")
    fail_data = {
        "ticker": "INVALID",
        "success": False,
        "current": None,
        "company": None,
        "historical": None,
        "errors": ["Failed to fetch current price", "Failed to fetch company info"]
    }
    
    result = validate_stock_data(fail_data)
    print(f"{result['badge']['emoji']} Confidence: {result['confidence_level']} ({result['confidence_score']}%)")
    print(f"Valid: {result['valid']}")
    print(f"Missing: {result['missing_data']}")
    print(f"Recommendation: {result['recommendation']}")
    
    print("\n" + "="*60)
    print("✓ All validator tests complete")
    print("="*60)
