"""
Finance Assistant - Intent Parser
Uses Claude API to extract structured intent from user questions
Fail-closed: Returns success=False if confidence < 70%
"""

import os
import json
from typing import Dict, Optional
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Anthropic client
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Import supported tickers from config
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from config import SUPPORTED_TICKERS, is_ticker_supported


SYSTEM_PROMPT = """You are a financial intent parser. Extract structured information from user questions about stocks.

You must extract:
1. ticker (stock symbol, uppercase)
2. query_type (one of: current_performance, outlook, comparison, buy_recommendation, historical_performance)
3. timeframe (one of: today, this_week, this_month, this_year, long_term)
4. confidence (0-100, how confident you are in your extraction)

Rules:
- If no ticker is mentioned, set ticker to null
- If timeframe is unclear, default to "today" for current questions, "long_term" for outlook
- Be conservative with confidence - only 80+ if you're very sure
- If question is ambiguous or off-topic, set confidence < 70

Respond ONLY with valid JSON in this exact format:
{
  "ticker": "TSLA",
  "query_type": "current_performance",
  "timeframe": "today",
  "confidence": 85
}

Examples:
Q: "How's Tesla doing today?"
A: {"ticker": "TSLA", "query_type": "current_performance", "timeframe": "today", "confidence": 95}

Q: "What's the outlook for Apple?"
A: {"ticker": "AAPL", "query_type": "outlook", "timeframe": "long_term", "confidence": 90}

Q: "Should I buy NVDA?"
A: {"ticker": "NVDA", "query_type": "buy_recommendation", "timeframe": "today", "confidence": 95}

Q: "Compare Tesla and Apple"
A: {"ticker": "TSLA", "query_type": "comparison", "timeframe": "today", "confidence": 80}

Q: "What's for dinner?"
A: {"ticker": null, "query_type": null, "timeframe": null, "confidence": 0}
"""


def parse_intent(user_question: str, context: dict = None) -> Dict:
    """
    Parse user intent and extract ticker symbols.
    Now supports MULTI-TICKER comparisons.
    
    Returns:
        {
            'success': bool,
            'tickers': List[str],  # Now a LIST (can be 1-3 tickers)
            'query_type': str,
            'confidence': int,
            'error': str
        }
    """
    
    # Handle follow-up context
    if context and context.get('last_ticker'):
        # Check if user is responding to a comparison suggestion
        if user_question.lower().strip() in ['yes', 'yeah', 'sure', 'yeah sure', 'ok', 'okay']:
            # This will be handled by fallback handler
            pass
    
    system_prompt = f"""Extract stock ticker symbols and intent from the user's question.

SUPPORTED TICKERS (100 total): {', '.join(SUPPORTED_TICKERS[:20])}... and 80 more.

CRITICAL: The user may ask about MULTIPLE tickers for comparison.
Examples:
- "Compare TSLA to RIVN and LCID" → Extract: ["TSLA", "RIVN", "LCID"]
- "How does AAPL stack up against MSFT and GOOGL?" → Extract: ["AAPL", "MSFT", "GOOGL"]
- "NVDA vs AMD" → Extract: ["NVDA", "AMD"]

Return ONLY valid JSON:
{{
    "tickers": ["SYMBOL1", "SYMBOL2", ...],  // List of 1-3 tickers
    "query_type": "current_performance|outlook|buy_recommendation|comparison|historical_performance",
    "timeframe": "today|this_week|this_month|this_year|long_term",
    "confidence": 0-100
}}

Query types:
- comparison: User wants to compare multiple stocks
- buy_recommendation: "Should I buy", "Is X a good buy"
- current_performance: "How is X doing", "What's happening with X"
- outlook: "What's the outlook for X"
- historical_performance: "How has X performed"

CRITICAL:
- If ticker not in supported list → confidence = 0
- If question unclear → confidence < 70
- If multiple tickers mentioned → query_type = "comparison"
- Maximum 3 tickers per comparison
"""
    
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Question: {user_question}"}
            ]
        )
        
        response_text = message.content[0].text
        
        # Parse JSON (handle markdown code blocks)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        result = json.loads(response_text.strip())
        
        # Validate tickers (convert single ticker to list if needed)
        if isinstance(result.get('tickers'), str):
            result['tickers'] = [result['tickers']]
        
        tickers = result.get('tickers', [])
        confidence = result.get('confidence', 0)
        
        # Validate all tickers are supported
        valid_tickers = [t.upper() for t in tickers if t.upper() in SUPPORTED_TICKERS]
        
        if not valid_tickers:
            return {
                'success': False,
                'tickers': [],
                'error': 'No supported ticker symbols found',
                'confidence': 0
            }
        
        # Confidence check (fail-closed)
        if confidence < 70:
            return {
                'success': False,
                'tickers': valid_tickers,
                'error': f'Low confidence ({confidence}%). Question may be unclear or off-topic.',
                'confidence': confidence
            }
        
        # Success
        return {
            'success': True,
            'tickers': valid_tickers[:3],  # Max 3 tickers
            'query_type': result.get('query_type', 'current_performance'),
            'timeframe': result.get('timeframe', 'today'),
            'confidence': confidence
        }
        
    except Exception as e:
        print(f"✗ Intent parsing failed: {e}")
        return {
            'success': False,
            'tickers': [],
            'error': f'Failed to parse intent: {str(e)}',
            'confidence': 0
        }
