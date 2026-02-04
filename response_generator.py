# backend/response_generator.py
# ASCII-only. Claude response generator + deterministic next_actions.
#
# Changes vs prior:
# - Use the user's actual question when available (intent['question'] or intent['original_question'])
# - Remove forced "end with follow-up question" in system prompt (conversation continues naturally)
# - Return structured next_actions/default_action_id for deterministic follow-up routing
# - Fix duplicate _format_sources definition
# - Safer formatting for numeric fields (volume) and period-aware historical labels

import os
from anthropic import Anthropic
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional, Tuple

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# -----------------------------
# Public API
# -----------------------------

def generate_response(
    intent: Dict[str, Any],
    stock_data: Dict[str, Any],
    articles: List[Dict[str, Any]],
    validation: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate intelligent stock analysis using Claude API.

    Returns a response dict that now includes:
      - next_actions: list of {id,label,query,keywords}
      - default_action_id: action id string
    """

    context = _build_context(intent, stock_data, articles, validation)

    tickers = intent.get("tickers", []) or []
    ticker = tickers[0] if tickers else intent.get("ticker", "UNKNOWN")

    print(f"⏳ Generating analysis for {ticker}...")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=_get_system_prompt(validation.get("confidence_level", "LOW")),
            messages=[
                {"role": "user", "content": context}
            ],
        )

        response_text = message.content[0].text
        print(f"✓ Generated response ({len(response_text)} chars)")

        next_actions, default_action_id = _derive_next_actions(intent, ticker)

        return {
            "success": True,
            "answer": response_text,
            "confidence": validation.get("confidence_level", "LOW"),
            "confidence_score": validation.get("confidence_score", 0),
            "badge": validation.get("badge", {"emoji": "🔴", "color": "red", "message": "Low confidence"}),
            "sources": _format_sources(articles),
            "ticker": ticker,
            "query_type": intent.get("query_type"),
            "next_actions": next_actions,
            "default_action_id": default_action_id,
            "tokens_used": {
                "input": message.usage.input_tokens,
                "output": message.usage.output_tokens,
            },
        }

    except Exception as e:
        print(f"✗ Failed to generate response: {e}")
        return {
            "success": False,
            "error": f"Failed to generate analysis: {str(e)}",
            "confidence": "LOW",
            "confidence_score": 0,
        }


def generate_comparison_response(
    intent: Dict[str, Any],
    all_stock_data: Dict[str, Dict[str, Any]],
    all_articles: Dict[str, List[Dict[str, Any]]],
    overall_confidence: str,
    confidence_score: int
) -> Dict[str, Any]:
    """
    Generate comparative analysis for multiple tickers.
    Now also returns next_actions/default_action_id for follow-ups.
    """

    tickers = list(all_stock_data.keys())
    print(f"⏳ Generating comparison for {', '.join(tickers)}...")

    question_text = (
        intent.get("question")
        or intent.get("original_question")
        or intent.get("raw_question")
        or f"Compare {', '.join(tickers[:-1])} and {tickers[-1]}"
    )

    context = f"User Question: {question_text}\n\n"
    context += "---\n\n"

    for t in tickers:
        stock_data = all_stock_data.get(t, {})
        articles = all_articles.get(t, [])

        context += f"{t} DATA:\n"

        current = stock_data.get("current", {})
        if current:
            context += f"Price: ${current.get('current_price', 'N/A')}\n"
            context += f"Change: {current.get('change_percent', 'N/A')}%\n"
            context += f"Volume: {_fmt_int(current.get('volume'))}\n"

        company = stock_data.get("company", {})
        if company:
            context += f"Company: {company.get('company_name', 'N/A')}\n"
            context += f"Sector: {company.get('sector', 'N/A')}\n"

        historical = stock_data.get("historical", {})
        if historical:
            context += f"Return: {historical.get('total_return', 'N/A')}%\n"
            context += f"Range: ${historical.get('low', 'N/A')} - ${historical.get('high', 'N/A')}\n"

        if articles:
            context += f"Recent articles: {len(articles)} found\n"
            for a in articles[:2]:
                context += f"  - {a.get('title','')[:70]}... ({a.get('source','')})\n"

        context += "\n"

    context += f"---\n\nDATA CONFIDENCE: {overall_confidence} ({confidence_score}%)\n"
    context += "\n\n---\nFORMATTING INSTRUCTION: Use \\n\\n (actual newlines) between each paragraph for readability.\n"

    system_prompt = """You are comparing multiple stocks. Provide a clear, comparative analysis grounded in the data provided.

CRITICAL FORMATTING:
- Use DOUBLE LINE BREAKS between paragraphs
- Keep paragraphs to 2-3 sentences max
- Make it scannable and easy to read

STRUCTURE:
1) Quick comparison snapshot (price/performance) with concrete numbers
2) Key differences (business model, sector exposure, valuation sensitivity, catalysts)
3) Comparative judgment: which looks better for different profiles (risk-seeking vs conservative)
4) End naturally. Do NOT force a scripted follow-up question.

Guidelines:
- Be direct and specific
- Cite numbers and call out what data is missing
- Reference articles by source when relevant
"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            messages=[
                {"role": "user", "content": context}
            ],
        )

        response_text = message.content[0].text
        print(f"✓ Generated comparison ({len(response_text)} chars)")

        all_sources: List[Dict[str, Any]] = []
        for t, arts in all_articles.items():
            for a in (arts or [])[:2]:
                all_sources.append({
                    "title": f"[{t}] {a.get('title','')}",
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "date": a.get("date", ""),
                })

        badge = _confidence_badge(overall_confidence)

        # Next actions: drill into a ticker, or widen comparison
        next_actions, default_action_id = _derive_comparison_next_actions(tickers)

        return {
            "success": True,
            "answer": response_text,
            "confidence": overall_confidence,
            "confidence_score": confidence_score,
            "badge": badge,
            "sources": all_sources[:8],
            "tickers": tickers,
            "next_actions": next_actions,
            "default_action_id": default_action_id,
            "tokens_used": {
                "input": message.usage.input_tokens,
                "output": message.usage.output_tokens,
            },
        }

    except Exception as e:
        print(f"✗ Failed to generate comparison: {e}")
        return {
            "success": False,
            "error": f"Failed to generate comparison: {str(e)}",
            "confidence": "LOW",
            "confidence_score": 0,
        }


# -----------------------------
# Context builder
# -----------------------------

def _build_context(intent: Dict[str, Any], stock_data: Dict[str, Any], articles: List[Dict[str, Any]], validation: Dict[str, Any]) -> str:
    tickers = intent.get("tickers", []) or []
    ticker = tickers[0] if tickers else intent.get("ticker", "UNKNOWN")

    # Use the actual user question if available
    question_text = (
        intent.get("question")
        or intent.get("original_question")
        or intent.get("raw_question")
    )
    if not question_text:
        # fallback to prior behavior, but still query_type-aware
        query_type = intent.get("query_type", "general")
        if query_type == "current_performance":
            question_text = f"How is {ticker} performing today?"
        elif query_type == "outlook":
            question_text = f"What's the outlook for {ticker}?"
        elif query_type == "buy_recommendation":
            question_text = f"Should I buy {ticker}?"
        elif query_type == "historical_performance":
            question_text = f"How has {ticker} performed historically?"
        else:
            question_text = f"Analyze {ticker} stock"

    context = f"User Question: {question_text}\n\n---\n\n"

    current = stock_data.get("current", {}) or {}
    if current:
        context += "CURRENT DATA:\n"
        context += f"Price: ${current.get('current_price', 'N/A')}\n"
        context += f"Change: {current.get('change', 'N/A')} ({current.get('change_percent', 'N/A')}%)\n"
        context += f"Volume: {_fmt_int(current.get('volume'))}\n"
        context += f"Day Range: ${current.get('day_low', 'N/A')} - ${current.get('day_high', 'N/A')}\n\n"

    company = stock_data.get("company", {}) or {}
    if company:
        context += "COMPANY INFO:\n"
        context += f"Name: {company.get('company_name', 'N/A')}\n"
        context += f"Sector: {company.get('sector', 'N/A')}\n"
        context += f"Industry: {company.get('industry', 'N/A')}\n"
        if company.get("description"):
            desc = str(company.get("description"))
            context += f"Description: {desc[:200]}...\n"
        context += "\n"

    historical = stock_data.get("historical", {}) or {}
    if historical:
        # If the upstream data layer attaches a label/period, use it
        hist_label = (
            historical.get("period_label")
            or intent.get("period")
            or intent.get("timeframe")
            or "Past Year"
        )
        context += f"HISTORICAL PERFORMANCE ({hist_label}):\n"
        context += f"Total Return: {historical.get('total_return', 'N/A')}%\n"
        context += f"Range: ${historical.get('low', 'N/A')} - ${historical.get('high', 'N/A')}\n"
        context += f"Data Points: {historical.get('data_points', 'N/A')}\n\n"

    if articles:
        context += f"RECENT ANALYSIS & NEWS ({len(articles)} articles):\n"
        for i, a in enumerate(articles, 1):
            context += f"\n[{i}] {a.get('title','')}\n"
            context += f"    Source: {a.get('source','')} ({a.get('date','')})\n"
            snip = a.get("snippet")
            if snip:
                context += f"    {str(snip)[:150]}...\n"
        context += "\n"

    context += "---\n\n"
    conf_level = validation.get("confidence_level", "LOW")
    conf_score = validation.get("confidence_score", 0)
    context += f"DATA CONFIDENCE: {conf_level} ({conf_score}%)\n"

    missing = validation.get("missing_data") or []
    if missing:
        # keep it short
        preview = ", ".join(str(x) for x in missing[:3])
        context += f"Missing: {preview}\n"

    context += "\n\n---\nFORMATTING INSTRUCTION: Use \\n\\n (actual newlines) between each paragraph for readability.\n"
    return context


# -----------------------------
# System prompt
# -----------------------------

def _get_system_prompt(confidence_level: str) -> str:
    base_prompt = """You are a private-mode financial analysis assistant. Provide clear, direct stock analysis based on the data provided.

CRITICAL FORMATTING:
- Use DOUBLE LINE BREAKS between paragraphs
- Keep paragraphs to 2-3 sentences max
- Use clear sections when helpful (avoid excessive headers)
- Make it scannable and easy to read

CRITICAL BEHAVIOR:
- Make judgments when warranted
- Always justify judgments with numbers, data, or explicit assumptions
- Call out what is missing if it changes the conclusion
- Reference article sources when relevant
- End naturally based on the analysis. Do NOT force a scripted follow-up question.

SUGGESTED STRUCTURE (adapt as needed):
1) Current situation (price/action + what matters)
2) Key drivers (bull vs bear)
3) Key considerations and trade-offs (scenarios and conditions, not recommendations)
"""

    cl = (confidence_level or "LOW").upper()
    if cl == "HIGH":
        base_prompt += "\n- Data quality is high: be specific and decisive where evidence supports it."
    elif cl == "MEDIUM":
        base_prompt += "\n- Some data missing: acknowledge gaps, but still provide a usable judgment."
    else:
        base_prompt += "\n- Data quality is low: be cautious and highlight the key missing pieces."

    return base_prompt


# -----------------------------
# Next-actions derivation
# -----------------------------

def _derive_next_actions(intent: Dict[str, Any], ticker: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Deterministic next actions for follow-up routing.
    These are NOT shown to the user necessarily; main.py should store them in memory.
    """

    qt = (intent.get("query_type") or "general").lower()
    t = (ticker or "UNKNOWN").upper()

    actions: List[Dict[str, Any]] = []

    # Universal options for single-ticker analyses
    actions.append({
        "id": "deep_dive_key_risks",
        "label": f"Go deeper on {t} risks and what would break the thesis",
        "query": f"Dive deeper into {t}: key risks, main failure modes, and what would change your view.",
        "keywords": ["risk", "break", "failure", "downside"],
    })

    # Query-type specific actions
    if qt in ("outlook", "buy_recommendation"):
        actions.insert(0, {
            "id": "deep_dive_earnings",
            "label": f"Dive deeper into {t} earnings and forward drivers",
            "query": f"Dive deeper into {t}: latest earnings takeaways, guidance, and the next 1-2 catalysts that matter.",
            "keywords": ["earnings", "guidance", "catalyst", "q4", "quarter"],
        })
        actions.append({
            "id": "valuation_sanity_check",
            "label": f"Run a valuation sanity-check on {t}",
            "query": f"Sanity-check {t} valuation vs growth and risks. What assumptions are priced in?",
            "keywords": ["valuation", "pe", "multiple", "priced in"],
        })

    if qt == "historical_performance":
        actions.insert(0, {
            "id": "regime_breakdown",
            "label": f"Break {t} history into regimes (runs, drawdowns, catalysts)",
            "query": f"Break down {t} historical performance into major regimes: run-ups, drawdowns, and what drove each.",
            "keywords": ["history", "regime", "drawdown", "cycle"],
        })

    if qt == "current_performance":
        actions.insert(0, {
            "id": "what_moved_today",
            "label": f"Explain what moved {t} today",
            "query": f"What likely moved {t} today? Tie price action to news, sector moves, and any known catalysts.",
            "keywords": ["today", "move", "news", "why"],
        })

    # If TSLA, a very common follow-up is EV valuation compare
    if t == "TSLA":
        actions.append({
            "id": "compare_ev_valuation",
            "label": "Compare TSLA valuation vs other EV/auto manufacturers",
            "query": "Compare TSLA valuation metrics and narrative vs major auto/EV peers (GM, F, RIVN, LCID). What looks most mispriced and why?",
            "keywords": ["compare", "ev", "peers", "gm", "ford", "rivn", "lcid", "valuation"],
        })

    # Keep it small: top 3 actions only
    actions = actions[:3]

    default_action_id = actions[0]["id"] if actions else "deep_dive_key_risks"
    return actions, default_action_id


def _derive_comparison_next_actions(tickers: List[str]) -> Tuple[List[Dict[str, Any]], str]:
    ts = [str(x).upper() for x in (tickers or []) if str(x).strip()]
    label = ", ".join(ts) if ts else "these"

    actions: List[Dict[str, Any]] = [
        {
            "id": "pick_best_by_profile",
            "label": f"Choose the best of {label} for different investor profiles",
            "query": f"Given {', '.join(ts)}, pick which fits best for: (1) aggressive growth, (2) balanced long-term, (3) conservative. Justify with data.",
            "keywords": ["profile", "best", "conservative", "aggressive", "balanced"],
        },
        {
            "id": "deep_dive_first_ticker",
            "label": f"Deep dive {ts[0]} (thesis, risks, catalysts)" if ts else "Deep dive the first ticker",
            "query": f"Deep dive {ts[0]}: thesis, risks, catalysts, and what must go right." if ts else "Deep dive the first ticker: thesis, risks, catalysts.",
            "keywords": ["deep", "dive", "thesis", "catalyst", "risk"],
        },
        {
            "id": "add_competitor",
            "label": "Add one competitor and rerun the comparison",
            "query": f"Add one relevant competitor to the {', '.join(ts)} comparison and rerun the assessment." if ts else "Add one competitor and rerun the comparison.",
            "keywords": ["add", "competitor", "rerun", "comparison"],
        },
    ]

    default_action_id = actions[0]["id"]
    return actions, default_action_id


# -----------------------------
# Helpers
# -----------------------------

def _format_sources(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for a in (articles or [])[:5]:
        sources.append({
            "title": a.get("title", ""),
            "source": a.get("source", ""),
            "url": a.get("url", ""),
            "date": a.get("date", ""),
        })
    return sources


def _confidence_badge(conf: str) -> Dict[str, str]:
    c = (conf or "LOW").upper()
    if c == "HIGH":
        return {"emoji": "🟢", "color": "green", "message": "High confidence"}
    if c == "MEDIUM":
        return {"emoji": "🟡", "color": "yellow", "message": "Medium confidence"}
    return {"emoji": "🔴", "color": "red", "message": "Low confidence"}


def _fmt_int(v: Any) -> str:
    try:
        if v is None:
            return "N/A"
        if isinstance(v, str):
            if v.strip().upper() == "N/A":
                return "N/A"
            v = float(v.replace(",", ""))
        iv = int(v)
        return f"{iv:,}"
    except Exception:
        return "N/A"
