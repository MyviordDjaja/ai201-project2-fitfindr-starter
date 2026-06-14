"""
Tests for the three FitFindr tools.

Run from the project root with:
    pytest tests/

The search_listings tests are pure/local and always run. The suggest_outfit
and create_fit_card tests that hit the Groq LLM are skipped automatically if
GROQ_API_KEY is not set, so the suite still passes offline.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

needs_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live LLM test",
)


# ── search_listings (pure / local) ────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_substring():
    # "M" should match listings whose size contains it, e.g. "S/M", "M/L".
    results = search_listings("top", size="M", max_price=None)
    assert results, "expected at least one size-M-ish top"
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    # Most relevant first: scores should be non-increasing across results.
    results = search_listings("vintage band tee", size=None, max_price=None)
    assert len(results) >= 2
    # The top result should be a tee, not an unrelated item.
    assert "tee" in results[0]["title"].lower()


def test_search_no_keywords_still_filters_by_price():
    # Only stopwords as keywords → keep everything under the price ceiling.
    results = search_listings("the", size=None, max_price=15)
    assert results, "expected cheap items to come through"
    assert all(item["price"] <= 15 for item in results)


# ── suggest_outfit (LLM) ──────────────────────────────────────────────────────

@needs_groq
def test_suggest_outfit_with_wardrobe():
    new_item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(new_item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


@needs_groq
def test_suggest_outfit_empty_wardrobe_does_not_crash():
    # Failure mode: empty wardrobe still returns useful, non-empty advice.
    new_item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(new_item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


# ── create_fit_card (LLM + guard) ─────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_message():
    # Failure mode: incomplete outfit → descriptive string, no exception, no API.
    new_item = {"title": "Faded Band Tee", "price": 22, "platform": "depop"}
    result = create_fit_card("", new_item)
    assert isinstance(result, str)
    assert result.strip() != ""
    # It should be the guard message, not a real caption.
    assert "without an outfit" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_message():
    new_item = {"title": "Faded Band Tee", "price": 22, "platform": "depop"}
    result = create_fit_card("   \n  ", new_item)
    assert "without an outfit" in result.lower()


@needs_groq
def test_create_fit_card_valid_outfit():
    new_item = {"title": "Faded Band Tee", "price": 22, "platform": "depop"}
    outfit = "Wear it with baggy jeans and chunky sneakers for a 90s grunge look."
    card = create_fit_card(outfit, new_item)
    assert isinstance(card, str)
    assert card.strip() != ""


@needs_groq
def test_create_fit_card_outputs_vary():
    # High temperature → repeated runs on the same input should differ.
    new_item = {"title": "Faded Band Tee", "price": 22, "platform": "depop"}
    outfit = "Wear it with baggy jeans and chunky sneakers for a 90s grunge look."
    a = create_fit_card(outfit, new_item)
    b = create_fit_card(outfit, new_item)
    assert a != b
