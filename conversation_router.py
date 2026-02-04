# backend/conversation_router.py
# ASCII-only. Deterministic follow-up routing for "yeah / do that / first one" style replies.
#
# Goal:
# - If user message is a continuation/ack, route to stored next_actions in conversation memory.
# - Avoid scraping last_response text.
# - Keep this module pure: no network calls, no LLM calls, no I/O.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# Public data shapes
# -----------------------------

@dataclass(frozen=True)
class FollowupAction:
    """A structured next step the system suggested previously."""
    id: str
    label: str
    query: str  # explicit query to run if selected
    keywords: Tuple[str, ...] = ()  # optional keyword hints


@dataclass(frozen=True)
class FollowupResolution:
    """Result of resolving a user message against stored followups."""
    kind: str  # "action" | "clarify" | "none"
    action: Optional[FollowupAction] = None
    clarify_prompt: Optional[str] = None
    confidence: int = 0  # 0-100
    reason: str = ""


# -----------------------------
# Normalization utilities
# -----------------------------

_WORD_RE = re.compile(r"[a-z0-9']+")

def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    # unify common apostrophes
    s = s.replace("’", "'")
    # drop noisy punctuation to spaces
    s = re.sub(r"[^a-z0-9'\s]+", " ", s)
    # squeeze spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokens(s: str) -> List[str]:
    s = _normalize_text(s)
    return _WORD_RE.findall(s)


# -----------------------------
# Continuation / ack detection
# -----------------------------

# Prefixes / phrases that imply "continue / accept / do the suggested thing"
_ACK_PREFIXES = (
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "k", "kk",
    "sounds good", "do that", "do it", "lets do that", "let's do that",
    "lets do it", "let's do it", "go ahead", "continue", "keep going",
    "dive in", "dive deeper", "lets dive", "let's dive", "run it",
    "sounds right", "that works", "fine", "alright", "all right",
)

# Short replies that are typically acknowledgements
_ACK_SINGLETONS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright", "go", "do", "doit", "continue"}

def is_ack_or_continue(user_text: str) -> bool:
    """True if user message is likely 'continue with what you just proposed'."""
    t = _normalize_text(user_text)
    if not t:
        return False
    if t in _ACK_SINGLETONS:
        return True
    # Check startswith common acceptance prefixes
    for p in _ACK_PREFIXES:
        if t.startswith(p):
            return True
    # Heuristic: very short + contains acceptance token
    toks = _tokens(t)
    if len(toks) <= 4 and any(x in ("yes", "yeah", "yep", "sure", "ok", "okay", "alright") for x in toks):
        return True
    return False


# -----------------------------
# Option picking helpers
# -----------------------------

_ORDINAL_MAP = {
    "first": 0, "1st": 0, "one": 0,
    "second": 1, "2nd": 1, "two": 1,
    "third": 2, "3rd": 2, "three": 2,
    "fourth": 3, "4th": 3, "four": 3,
}

def _ordinal_pick(user_text: str) -> Optional[int]:
    t = _tokens(user_text)
    for w in t:
        if w in _ORDINAL_MAP:
            return _ORDINAL_MAP[w]
    # also match "option 1", "choice 2"
    m = re.search(r"\b(option|choice)\s*(\d)\b", _normalize_text(user_text))
    if m:
        idx = int(m.group(2)) - 1
        if idx >= 0:
            return idx
    return None

def _score_action_match(user_text: str, action: FollowupAction) -> int:
    """
    Deterministic keyword scoring:
    - match action.id tokens
    - match action.keywords
    - match label tokens
    """
    utoks = set(_tokens(user_text))
    if not utoks:
        return 0

    score = 0

    # action.id tokens (split on non-alnum / underscores)
    id_toks = set(re.findall(r"[a-z0-9]+", (action.id or "").lower()))
    score += 4 * len(utoks.intersection(id_toks))

    # explicit keywords (strong signal)
    for kw in action.keywords or ():
        kw_toks = set(_tokens(kw))
        if kw_toks and kw_toks.issubset(utoks):
            score += 10
        else:
            score += 3 * len(utoks.intersection(kw_toks))

    # label tokens (weak signal)
    label_toks = set(_tokens(action.label or ""))
    score += 2 * len(utoks.intersection(label_toks))

    return score


# -----------------------------
# Main resolver
# -----------------------------

def _load_actions_from_memory(last_context: Dict[str, Any]) -> Tuple[List[FollowupAction], Optional[str]]:
    """
    Expected memory shape (recommended):
      last_context["next_actions"] = [
        {"id": "...", "label": "...", "query": "...", "keywords": ["...","..."]},
        ...
      ]
      last_context["default_action_id"] = "..."
    """
    actions_raw = (last_context or {}).get("next_actions") or []
    default_id = (last_context or {}).get("default_action_id")

    actions: List[FollowupAction] = []
    for a in actions_raw:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "").strip()
        label = str(a.get("label") or "").strip()
        query = str(a.get("query") or "").strip()
        if not aid or not query:
            continue
        kws = a.get("keywords") or []
        if isinstance(kws, str):
            kws = [kws]
        keywords = tuple(str(x).strip() for x in kws if str(x).strip())
        actions.append(FollowupAction(id=aid, label=label, query=query, keywords=keywords))

    # If default_id missing but there are actions, choose first as default.
    if (not default_id) and actions:
        default_id = actions[0].id

    return actions, default_id


def resolve_followup(user_text: str, last_context: Dict[str, Any]) -> FollowupResolution:
    """
    Resolve a user continuation message against structured followups in memory.

    Returns:
      - kind="action" with FollowupAction if resolved
      - kind="clarify" with clarify_prompt if ambiguous
      - kind="none" if not a followup / no actions available
    """
    actions, default_id = _load_actions_from_memory(last_context)
    if not actions:
        return FollowupResolution(kind="none", confidence=0, reason="no next_actions in memory")

    # 1) Ordinal selection: "first one", "option 2"
    ord_idx = _ordinal_pick(user_text)
    if ord_idx is not None and 0 <= ord_idx < len(actions):
        return FollowupResolution(
            kind="action",
            action=actions[ord_idx],
            confidence=90,
            reason=f"ordinal_pick={ord_idx}",
        )

    # 2) Keyword-based selection
    scored = [(a, _score_action_match(user_text, a)) for a in actions]
    scored.sort(key=lambda x: x[1], reverse=True)
    best, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0

    # If strong match and clear margin, pick it
    if best_score >= 8 and best_score >= (second_score + 3):
        return FollowupResolution(
            kind="action",
            action=best,
            confidence=85,
            reason=f"keyword_match score={best_score} margin={best_score-second_score}",
        )

    # 3) Pure acceptance: "yeah do that" -> default action
    if is_ack_or_continue(user_text) and default_id:
        for a in actions:
            if a.id == default_id:
                return FollowupResolution(
                    kind="action",
                    action=a,
                    confidence=80,
                    reason="ack_or_continue -> default_action",
                )
        # fallback: first action
        return FollowupResolution(
            kind="action",
            action=actions[0],
            confidence=70,
            reason="ack_or_continue -> default missing -> first_action",
        )

    # 4) Ambiguous: ask a tight clarifier listing options
    # Keep it short; calling code can choose to ask user or default.
    options = [a.label or a.id for a in actions[:3]]
    opt_text = "; ".join(f"{i+1}) {x}" for i, x in enumerate(options))
    return FollowupResolution(
        kind="clarify",
        clarify_prompt=f"Quick check: which one did you mean — {opt_text}?",
        confidence=40,
        reason=f"ambiguous best_score={best_score} second_score={second_score}",
    )


# Convenience helper for callers that want a simple result
def resolve_followup_query(user_text: str, last_context: Dict[str, Any]) -> Tuple[Optional[str], FollowupResolution]:
    """
    Returns (query, resolution). query is the explicit follow-up query if resolved.
    """
    res = resolve_followup(user_text, last_context)
    if res.kind == "action" and res.action:
        return res.action.query, res
    return None, res
