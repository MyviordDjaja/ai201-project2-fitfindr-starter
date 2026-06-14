"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Groq model used by the two LLM-backed tools.
MODEL = "llama-3.3-70b-versatile"

# Common filler words to ignore when scoring keyword relevance, so a query like
# "looking for a vintage tee" scores on "vintage"/"tee", not "for"/"a".
_STOPWORDS = {
    "a", "an", "the", "for", "with", "and", "or", "of", "to", "in", "on",
    "under", "below", "less", "than", "looking", "want", "wanted", "need",
    "size", "my", "i", "im", "mostly", "wear", "some", "something", "any",
    "that", "this", "is", "are", "it", "me", "show", "find", "get",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into alphanumeric word tokens."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Query keywords, minus filler words. If nothing meaningful is left we keep
    # every (filtered) listing rather than dropping them all.
    query_tokens = [t for t in _tokenize(description) if t not in _STOPWORDS]
    size_needle = size.lower().strip() if size else None

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Price filter (inclusive).
        if max_price is not None and listing["price"] > max_price:
            continue

        # Size filter — case-insensitive substring match, e.g. "M" in "S/M".
        if size_needle and size_needle not in listing["size"].lower():
            continue

        # Relevance: how many query keywords appear in the listing's text,
        # with a bonus for matches in the title or style tags.
        haystack = " ".join([
            listing["title"],
            listing["description"],
            " ".join(listing["style_tags"]),
            listing["category"],
            " ".join(listing["colors"]),
        ]).lower()
        title_tokens = set(_tokenize(listing["title"]))
        tag_tokens = set(_tokenize(" ".join(listing["style_tags"])))

        score = 0
        for tok in query_tokens:
            if tok in haystack:
                score += 1
                if tok in title_tokens:
                    score += 2
                if tok in tag_tokens:
                    score += 2

        # With no usable keywords, surface everything that passed the filters.
        if not query_tokens:
            score = 1

        if score > 0:
            scored.append((score, listing))

    # Highest score first; stable so equal scores keep dataset order.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item.get('title', 'this item')} "
        f"(category: {new_item.get('category', 'unknown')}; "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}; "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = (wardrobe or {}).get("items", [])

    if not items:
        # Empty wardrobe: general styling advice, no nonexistent pieces named.
        prompt = (
            f"A shopper is considering buying this secondhand piece:\n{item_desc}\n\n"
            "They haven't told you what's in their wardrobe yet. In 2-4 sentences, "
            "give general styling advice: what kinds of pieces and shoes pair well "
            "with it, and what overall vibe or occasion it suits. Speak directly to "
            "the shopper. Do NOT invent specific items you can't know they own."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it.get('name', 'item')}"
            f" ({it.get('category', '?')}; {', '.join(it.get('colors', [])) or 'n/a'})"
            + (f" — {it['notes']}" if it.get("notes") else "")
            for it in items
        )
        prompt = (
            f"A shopper is considering buying this secondhand piece:\n{item_desc}\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new piece with specific items "
            "from their wardrobe, naming those pieces exactly. Keep it to 2-4 sentences "
            "and end with one short styling tip. Speak directly to the shopper."
        )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are FitFindr, a warm, practical secondhand-fashion stylist.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no usable outfit → return a message, never crash.
    if not outfit or not outfit.strip():
        return "Can't write a fit card without an outfit suggestion — find an outfit first."

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "a resale app")

    prompt = (
        f"Write a short, casual social-media caption (an OOTD / fit-check post) for a "
        f"thrifted find.\n\n"
        f"Item: {title}\nPrice: {price_str}\nPlatform: {platform}\n"
        f"Outfit it's styled in: {outfit}\n\n"
        "Rules: 2-4 sentences, sound like a real person posting their fit (not a product "
        f"description). Mention the item, the price ({price_str}), and the platform "
        f"({platform}) naturally, once each. Capture the outfit's vibe in specific terms. "
        "Emoji are welcome. Return only the caption."
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You write punchy, authentic secondhand-fashion captions.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=1.1,  # high temperature so repeated runs vary
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()
