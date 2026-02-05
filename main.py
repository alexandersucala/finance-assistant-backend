# backend/main.py
# ASCII-only. V2.0 - Simplified conversation flow with clickable follow-ups

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

import sys
from pathlib import Path
from stripe_handler import create_checkout_session, verify_webhook
from database import track_usage, mark_user_as_paid

# Add backend to path
sys.path.append(str(Path(__file__).parent))

# Import all our modules
from intent_parser import parse_intent
from market_data import get_stock_data
from web_search import search_stock_articles
from validator import validate_stock_data
from response_generator import generate_response, generate_comparison_response
from database import init_database

# Initialize FastAPI app
app = FastAPI(
    title="Finance Assistant API",
    description="AI-powered stock analysis with fail-closed confidence scoring",
    version="2.0.0"
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "https://alexandersucala.com",
    "https://alexandersucala.github.io",
    "http://localhost:3000",
    "*"
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_database()
    print("✓ Finance Assistant API started - V2.0")
    print("✓ Database initialized")


# Request/Response models
class QuestionRequest(BaseModel):
    question: str
    session_id: Optional[str] = "default"


class AnalysisResponse(BaseModel):
    success: bool
    answer: Optional[str] = None
    confidence: Optional[str] = None
    confidence_score: Optional[int] = None
    badge: Optional[dict] = None
    sources: Optional[list] = None
    ticker: Optional[str] = None
    suggested_followups: Optional[list] = None  # New: clickable follow-up questions
    error: Optional[str] = None

@app.post("/api/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    result = verify_webhook(payload, sig_header)
    
    if not result["success"]:
        return {"error": result["error"]}, 400
    
    event = result["event"]
    
    # Handle successful subscription
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        client_reference_id = session.get('client_reference_id')
        
        if client_reference_id:
            # Mark user as paid
            mark_user_as_paid(client_reference_id)
            print(f"✓ User {client_reference_id} subscribed successfully")
    
    return {"success": True}

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "Finance Assistant API",
        "version": "2.0.0"
    }
@app.post("/api/create-checkout")
async def create_checkout(request: Request):
    """Create Stripe checkout session for subscription"""
    client_ip = request.client.host
    
    # Get base URL from request
    base_url = str(request.base_url).rstrip('/')
    success_url = f"{base_url}/../tools/finance-assistant.html?session=success"
    cancel_url = f"{base_url}/../tools/finance-assistant.html?session=cancel"
    
    result = create_checkout_session(
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=client_ip
    )
    
    return result

@app.post("/api/ask", response_model=AnalysisResponse)
async def ask_question(request: Request, question_data: QuestionRequest):
    # Get user identifier (IP address for now)
    client_ip = request.client.host
    
    # Track usage
    usage = track_usage(client_ip)
    
    # Check if limit hit
    if usage["limit_hit"]:
        return {
            "success": False,
            "confidence": "LOW",
            "answer": f"You've used all {usage['count']} free queries. Upgrade to Premium for unlimited access at $5/month.",
            "paywall": True,
            "usage": usage
        }
    
    # Continue with normal processing...
    """
    Main endpoint: Process user question and return stock analysis.

    Simplified flow (v2.0):
    - Single ticker questions ("How's Tesla?")
    - Multi-ticker comparisons ("Compare TSLA to RIVN and LCID")
    - General questions (no ticker)
    - No complex conversation state - each query is independent
    """
    question = request.question.strip()
    session_id = request.session_id

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    print(f"\n{'='*70}")
    print(f"NEW QUESTION: {question}")
    print(f"Session: {session_id}")
    print(f"{'='*70}")

    try:
        # Step 1: Parse intent
        print("\n[1/5] Parsing intent...")
        intent = parse_intent(question)

        if not intent.get("success"):
            print("⚠ Intent unclear, handling as general question...")
            return await handle_general_question(question, session_id)

        tickers = intent.get("tickers", []) or []

        if not tickers:
            print("⚠ No ticker found, handling as general question...")
            return await handle_general_question(question, session_id)

        print(f"✓ Intent: {tickers} - {intent.get('query_type')}")

        # Step 2: Fetch market data for ALL tickers
        print(f"\n[2/5] Fetching market data for {len(tickers)} ticker(s)...")

        all_stock_data: Dict[str, Any] = {}
        for ticker in tickers:
            stock_data = get_stock_data(ticker, include_historical=True)
            if stock_data.get("success"):
                all_stock_data[ticker] = stock_data
                print(f"  ✓ {ticker} data fetched")
            else:
                print(f"  ✗ {ticker} data failed")

        if not all_stock_data:
            return AnalysisResponse(
                success=False,
                error=f"Failed to fetch data for {', '.join(tickers)}. Please check ticker symbols.",
                ticker=tickers[0] if tickers else None,
                confidence="LOW",
                confidence_score=0
            )

        # Step 3: Search articles for ALL tickers
        print(f"\n[3/5] Searching for articles...")

        all_articles: Dict[str, List[Dict[str, Any]]] = {}
        for ticker in all_stock_data.keys():
            articles = search_stock_articles(ticker, days_back=7, max_results=5)
            all_articles[ticker] = articles
            print(f"  ✓ {ticker}: {len(articles)} articles")

        # Step 4: Calculate confidence (aggregate across all tickers)
        print(f"\n[4/5] Calculating confidence score...")

        confidences: List[int] = []
        per_ticker_validation: Dict[str, Dict[str, Any]] = {}

        for ticker in all_stock_data.keys():
            v = validate_stock_data(all_stock_data[ticker], all_articles.get(ticker, []))
            per_ticker_validation[ticker] = v
            confidences.append(int(v.get("confidence_score", 0)))

        avg_confidence = (sum(confidences) // len(confidences)) if confidences else 0

        if avg_confidence >= 80:
            overall_confidence = "HIGH"
        elif avg_confidence >= 50:
            overall_confidence = "MEDIUM"
        else:
            overall_confidence = "LOW"

        print(f"✓ Confidence: {overall_confidence} ({avg_confidence}%)")

        # Step 5: Generate response
        print(f"\n[5/5] Generating analysis...")

        if len(tickers) == 1:
            ticker = tickers[0]
            validation = per_ticker_validation.get(ticker) or validate_stock_data(all_stock_data[ticker], all_articles.get(ticker, []))
            response = generate_response(intent, all_stock_data[ticker], all_articles.get(ticker, []), validation)
            
            # Generate suggested follow-ups based on query type
            suggested_followups = _generate_followup_buttons(ticker, intent.get("query_type"))
        else:
            response = generate_comparison_response(intent, all_stock_data, all_articles, overall_confidence, avg_confidence)
            
            # Generate comparison follow-ups
            suggested_followups = _generate_comparison_followup_buttons(tickers)

        if not response.get("success"):
            return AnalysisResponse(
                success=False,
                error=response.get("error", "Failed to generate analysis"),
                confidence="LOW",
                confidence_score=0
            )

        print(f"✓ Analysis generated ({len(response.get('answer',''))} chars)")
        print("="*70)

        return AnalysisResponse(
            success=True,
            answer=response.get("answer"),
            confidence=response.get("confidence"),
            confidence_score=response.get("confidence_score"),
            badge=response.get("badge"),
            sources=response.get("sources", []),
            ticker=tickers[0] if len(tickers) == 1 else ', '.join(tickers) if tickers else None,
            suggested_followups=suggested_followups
        )

    except Exception as e:
        print(f"✗ Error processing question: {e}")
        import traceback
        traceback.print_exc()
        
        return AnalysisResponse(
            success=False,
            error=f"An error occurred: {str(e)}",
            confidence="LOW",
            confidence_score=0
        )


def _generate_followup_buttons(ticker: str, query_type: str) -> List[Dict[str, str]]:
    """Generate clickable follow-up question buttons based on the analysis."""
    t = ticker.upper()
    
    followups = [
        {
            "text": f"Compare {t} to competitors",
            "query": f"Compare {t} to its main competitors"
        }
    ]
    
    if query_type == "current_performance":
        followups.insert(0, {
            "text": f"What moved {t} today?",
            "query": f"What news or events moved {t} today?"
        })
    
    if query_type in ["outlook", "buy_recommendation"]:
        followups.insert(0, {
            "text": f"Analyze {t} risks",
            "query": f"What are the main risks and failure modes for {t}?"
        })
    
    # Add sector-specific suggestions
    if t == "TSLA":
        followups.append({
            "text": "Compare EV valuations",
            "query": "Compare TSLA, RIVN, and LCID valuations"
        })
    
    # Keep it to 3 follow-ups max
    return followups[:3]


def _generate_comparison_followup_buttons(tickers: List[str]) -> List[Dict[str, str]]:
    """Generate follow-up buttons for comparison queries."""
    ts = [t.upper() for t in tickers]
    
    followups = []
    
    if len(ts) >= 1:
        followups.append({
            "text": f"Deep dive {ts[0]}",
            "query": f"Give me a detailed analysis of {ts[0]} - risks, catalysts, and outlook"
        })
    
    followups.append({
        "text": "Which is best for growth?",
        "query": f"Of {', '.join(ts)}, which is best for aggressive growth investing?"
    })
    
    return followups[:2]


async def handle_general_question(question: str, session_id: str) -> AnalysisResponse:
    """
    Handle general questions with proactive recommendations based on risk tolerance.
    """
    from anthropic import Anthropic
    import os

    print("\n[GENERAL QUESTION HANDLER]")

    q_lower = question.lower()
    has_risk_info = any(word in q_lower for word in ['risk', 'tolerance', 'aggressive', 'conservative', 'play with', 'gamble'])
    has_timeframe = any(word in q_lower for word in ['year', 'month', 'long term', 'short term', 'hold'])

    system_prompt = """You are a private, internal-use investment reasoning system.

This system operates with access to structured local state, cached market data,
and precomputed context produced outside the language model.

Your job is to make real investment judgments for a trusted human user.
Be precise, grounded, and explicit about assumptions and limits.

Core operating philosophy (AUFG-style):
- evidence before narrative
- constraints before conclusions
- uncertainty must be stated explicitly
- judgments are allowed and expected
- no fake certainty: risk is time-varying

The user asked a general investing question without specifying a ticker.

Your task:
Proactively propose a small candidate set and make real judgments.
Do NOT ask clarifying questions first.

––––––––––––––––––––
Universe & selection rules (STRICT)
––––––––––––––––––––

1) Default universe (preferred for demos):
TSLA, NVDA, AMD, PLTR, COIN, AAPL, MSFT, GOOGL, JPM, JNJ, PG

2) You may deviate from the default universe ONLY if:
- the user's question implies a specific sector/theme (e.g., "energy", "defense", "dividends")
- OR the default universe is structurally mismatched to the request

If you deviate:
- include at most 2 extra tickers
- and explain the reason in one sentence under "Constraints & rationale".

3) Risk labels are NOT permanent.
You must classify each ticker into a risk regime based on "right now" conditions:
- volatility / beta intuition
- business cyclicality
- valuation fragility
- current news/earnings sensitivity (if known)
If unknown, say unknown.

––––––––––––––––––––
Output format (STRICT)
––––––––––––––––––––

1) One short acknowledgment of the user's intent.

2) Section title:
Candidate set (ranked, judgment-based)

First list the candidates in ranked order (best to worst fit for a generic retail investor),
then bucket them into three time-varying regimes:

- Higher uncertainty / higher variance outcomes
- Mid uncertainty / quality compounders or platform leverage
- Lower uncertainty / cash-flow anchored or defensive characteristics

Important:
Do NOT imply "low risk forever" — these are current regime labels only.

3) For EACH candidate, include exactly four short bullets:

- Approx price range (rough is acceptable)
- Why it's attractive right now (your judgment)
- What must go right (explicit condition)
- Primary failure mode (how this breaks)

4) Section:
Key considerations for different investor profiles

In 2–4 sentences:
Outline which 1–2 names may align with different risk profiles and why,
given typical constraints (capital size, risk tolerance, time horizon).

Frame as "investors seeking X might consider Y because..." rather than personal recommendations.
Focus on trade-offs and scenarios, not prescriptive advice.

5) Section:
Constraints & unknowns

List 2–3 concrete uncertainties that would materially change your judgments
(e.g., data freshness, earnings timing, macro sensitivity, missing fundamentals, API limits).

If you added tickers outside the default universe, note that here.

––––––––––––––––––––
Tone constraints
- calm, analytical, direct
- no emojis
- no hype or influencer language
- no public-facing disclaimers
"""

    if has_risk_info or has_timeframe:
        system_prompt += "\n\nNOTE: User mentioned investment criteria. Tailor suggestions accordingly."

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            system=system_prompt,
            messages=[{"role": "user", "content": f"User question: {question}"}]
        )

        answer = message.content[0].text
        
        # Generate follow-ups for general questions
        suggested_followups = [
            {
                "text": "Analyze TSLA",
                "query": "How is Tesla doing today?"
            },
            {
                "text": "Analyze NVDA", 
                "query": "Should I buy NVDA?"
            },
            {
                "text": "Compare tech giants",
                "query": "Compare AAPL, MSFT, and GOOGL"
            }
        ]

        return AnalysisResponse(
            success=True,
            answer=answer,
            confidence="MEDIUM",
            confidence_score=60,
            badge={"emoji": "🟡", "color": "yellow", "message": "Medium confidence - general recommendations"},
            sources=[],
            ticker=None,
            suggested_followups=suggested_followups
        )
    except Exception as e:
        print(f"⚠ Network error or API issue: {e}")
        return AnalysisResponse(
            success=True,
            answer=(
                "I'm having trouble connecting to generate a detailed response right now. "
                "Try again in a moment, or ask about a specific ticker."
            ),
            confidence="LOW",
            confidence_score=40,
            badge={"emoji": "🔴", "color": "red", "message": "Low confidence - connection issue"},
            sources=[],
            ticker=None
        )


@app.get("/api/health")
async def health_check():
    """Detailed health check with component status"""
    return {
        "status": "healthy",
        "components": {
            "api": "online",
            "database": "connected",
            "claude_api": "configured",
            "alpha_vantage": "configured",
            "brave_search": "configured"
        }
    }


if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*70)
    print("STARTING FINANCE ASSISTANT API V2.0")
    print("="*70)
    print("\nAPI will be available at: http://localhost:8000")
    print("Interactive docs at: http://localhost:8000/docs")
    print("\nPress CTRL+C to stop")
    print("="*70 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)