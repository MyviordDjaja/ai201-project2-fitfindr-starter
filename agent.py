"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

# "under $30", "below 30", "less than $30", "max 30", "< 30"
_PRICE_RE = re.compile(
    r"(?:under|below|less than|cheaper than|up to|max(?:imum)?|<)\s*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
# A bare dollar amount like "$30", used only if no "under/below" phrase is found.
_PRICE_FALLBACK_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
# "size M", "size 8", "size XXS"
_SIZE_RE = re.compile(r"\bsize\s+([A-Za-z0-9/]+)", re.IGNORECASE)
# Standalone, unambiguous size tokens like "US 8", "W30", "W30 L32"
_SIZE_STANDALONE_RE = re.compile(r"\b(US\s?\d+(?:\.5)?|W\d+(?:\s?L\d+)?)\b", re.IGNORECASE)


def _parse_query(query: str) -> dict:
    """
    Extract a description, optional size, and optional max_price from raw text.

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}.
    Matched price/size phrases are stripped out so they don't pollute the keywords.
    """
    text = query
    max_price = None
    size = None

    match = _PRICE_RE.search(text)
    if not match:
        match = _PRICE_FALLBACK_RE.search(text)
    if match:
        max_price = float(match.group(1))
        text = text[: match.start()] + " " + text[match.end():]

    match = _SIZE_RE.search(text)
    if match:
        size = match.group(1).strip(" .,")
        text = text[: match.start()] + " " + text[match.end():]
    else:
        match = _SIZE_STANDALONE_RE.search(text)
        if match:
            size = match.group(1).strip()
            text = text[: match.start()] + " " + text[match.end():]

    description = re.sub(r"\s+", " ", text).strip(" .,")
    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into description / size / max_price.
    parsed = _parse_query(query)
    session["parsed"] = parsed
    if not parsed["description"]:
        session["error"] = (
            "Tell me what kind of piece you're after — e.g. 'vintage denim jacket' "
            "or 'graphic tee under $30'."
        )
        return session

    # Step 3: search. Branch on the result — this is what makes the agent
    # respond differently to different inputs.
    results = search_listings(
        parsed["description"], size=parsed["size"], max_price=parsed["max_price"]
    )
    session["search_results"] = results
    if not results:
        # No match → set a helpful error and STOP. Do not call suggest_outfit.
        bits = [f"\"{parsed['description']}\""]
        if parsed["size"]:
            bits.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:g}")
        session["error"] = (
            "I couldn't find " + " ".join(bits) + ". Try broader keywords, a higher "
            "budget, or dropping the size filter."
        )
        return session

    # Step 4: select the top-ranked match.
    session["selected_item"] = results[0]

    # Step 5: suggest an outfit. Empty wardrobe is handled inside the tool, not
    # treated as an error here; a real LLM failure ends the run gracefully.
    try:
        session["outfit_suggestion"] = suggest_outfit(
            session["selected_item"], wardrobe
        )
    except Exception:
        session["error"] = (
            "I found a great piece but couldn't generate styling ideas right now — "
            "here's the listing; try again in a moment."
        )
        return session

    # Step 6: write the fit card from the outfit + selected item.
    try:
        session["fit_card"] = create_fit_card(
            session["outfit_suggestion"], session["selected_item"]
        )
    except Exception:
        session["error"] = (
            "I styled your piece but couldn't write the fit card right now — "
            "try again in a moment."
        )
        return session

    # Step 7: success — every output field is populated and error is None.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
