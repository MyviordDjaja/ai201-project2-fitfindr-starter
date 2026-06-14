# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock listings dataset for pieces that match the user's keywords, an optional size, and an optional price ceiling. It is fast, deterministic, and easy to test in isolation since no LLM calls are being made (only locally).

**Input parameters:**
It takes `description`, keywords describing what the user wants (e.g. `"vintage graphic tee"`), which get matched against each listing's `title`, `description`, `style_tags`, `category`, and `colors`; `size`, an optional size string like `"M"` matched case-insensitively and as a substring so `"M"` also catches `"S/M"` and `"M/L"` (or `None` to skip size filtering); and `max_price` (float | None, default `None`), an inclusive upper bound that keeps a listing only when `listing["price"] <= max_price` (or `None` to skip price filtering).

**What it returns:**
A `list[dict]` of full listing dicts, sorted by relevance score (highest first). Each dict keeps every original field: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`. Listings that pass the size/price filters but have a keyword-overlap score of 0 are dropped, so every returned item is relevant. Returns `[]` when nothing matches — it never raises.

**What happens if it fails or returns nothing:**
Returns an empty list `[]` rather than raising. It is the planning loop's job to detect the empty list, set a helpful `session["error"]`, and stop before calling `suggest_outfit`. The tool itself stays dumb and side-effect-free.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the one listing the user is considering and their wardrobe, and asks the LLM (Groq) to propose 1–2 concrete outfits, naming specific wardrobe pieces and giving a short styling tip. This is the only tool that needs the wardrobe.

**Input parameters:**
It takes `new_item` (dict, required), a single listing dict — the top search result the planning loop selected — whose `title`, `category`, `colors`, and `style_tags` feed the prompt; and `wardrobe` (dict, required), a wardrobe dict shaped `{"items": [...]}` where each item carries `id`, `name`, `category`, `colors`, `style_tags`, and an optional `notes`, and which may be empty (`{"items": []}`).

**What it returns:**
A non-empty `str` of natural-language styling advice. When the wardrobe has items, it references them by name, and when the wardrobe is empty, it returns general styling advice for the item instead of naming nonexistent items.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty it does NOT error — it switches to the general-advice prompt branch and still returns a useful string. If the LLM call itself raises (network/auth), the function lets the exception propagate to the planning loop, which catches it, records a friendly `session["error"]`, and skips `create_fit_card`.

---

### Tool 3: create_fit_card

**What it does:**
Turns the chosen item plus the outfit suggestion into a short, casual, social-media-ready caption using the LLM at a higher temperature so repeated runs feel fresh.

**Input parameters:**
It takes `outfit` (str, required), the styling string returned by `suggest_outfit()`; and `new_item` (dict, required), the same listing dict, used to weave the item's `title`, `price`, and `platform` naturally into the caption (once each).

**What it returns:**
A `str` of about 2–4 sentences usable directly as an Instagram/TikTok caption — casual voice, mentions the item name + price + platform once each, and captures the outfit vibe. Emoji are fine.

**What happens if it fails or returns nothing:**
First it guards: if `outfit` is `None`, empty, or whitespace-only, it returns a descriptive error string rather than raising. With a valid outfit, an LLM exception propagates to the planning loop to be recorded as `session["error"]`.

---

### Additional Tools (if any)

None for the core build. A possible stretch tool — `parse_query(query) -> dict` that extracts `description`/`size`/`max_price` from the raw user text via the LLM.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed, linear pipeline with early-exit error branches rather than a free-form "LLM picks a tool" loop; the order is always parse → search → select → suggest → fit card, and each step reads from and writes to the session dict, checking a guard before it advances. It starts by initializing a fresh session, then parses the raw query, pulling `max_price`, `size`, and `description`; if that description comes back empty it sets `session["error"]` asking what kind of piece the user is after and returns early. Next it calls `search_listings` and stores the result; if that list is empty, it sets a specific, actionable `session["error"]` and returns immediately without ever calling `suggest_outfit`, and otherwise it continues. It then selects the top-ranked match and calls `suggest_outfit(selected_item, wardrobe)` inside a `try/except`, treating an empty wardrobe not as an error but catching any LLM exception to set a friendly `session["error"]` and return before the fit card. Finally it calls `create_fit_card`, again inside a `try/except`, recording an error and returning on failure or storing the caption in `session["fit_card"]` on success. The loop knows it is finished when all three output fields are populated or when any guard has set `session["error"]`, and the caller (Gradio `handle_query`) checks `session["error"]` first — showing it in the listing panel and leaving the other two blank if it is set, or rendering all three panels if it is not.

---

## State Management

**How does information from one tool get passed to the next?**

All state for one interaction lives in a single session dict created by `_new_session` in `agent.py`; there is no global mutable state and nothing persists between calls to `run_agent`, so each request gets a fresh session that keeps runs isolated and testable. The tools themselves stay stateless — they receive exactly what they need as arguments and return a value the loop writes back into the session, which is the single source of truth and the thing handed to the UI. The session carries the original `query` and the `parsed` dict of `description`/`size`/`max_price` that the parse step fills and `search_listings` reads; the `search_results` list[dict] that the search step fills and the select step reads; the `selected_item` dict  that the select step copies from `search_results[0]` and that both LLM tools and the UI read; the `wardrobe` dict that `_new_session` sets from the UI choice and `suggest_outfit` reads; the `outfit_suggestion` string (or `None`) that the suggest step fills and `create_fit_card` and the UI read; the `fit_card` string (or `None`) that the fit-card step fills for the UI; and an `error` field (str or `None`) that any guard or `except` can set and that the UI checks first. The data therefore flows in one direction — `parsed` → `search_results` → `selected_item` → `outfit_suggestion` → `fit_card` — while `error` starts `None` and short-circuits everything downstream the moment it is set.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | When nothing matches, the loop sets `session["error"]` and stops before `suggest_outfit`, returning a message that names the parsed filters and offers concrete next steps — for example, "I couldn't find a 'designer ballgown' in size XXS under $5; try removing the size filter, raising your budget, or using broader keywords like 'dress' or 'formal'" — and sends nothing downstream. |
| suggest_outfit | Wardrobe is empty | This isn't treated as an error; the tool sees that `wardrobe["items"]` is empty, switches to a general-styling-advice prompt, and returns useful text, so the loop proceeds to `create_fit_card` normally and the user still gets all three panels. |
| suggest_outfit | LLM call raises (network/auth/rate-limit) | The loop's `try/except` catches it and sets `session["error"]` to something like "I found a great piece but couldn't generate styling ideas right now — here's the listing; try again in a moment," keeping `selected_item` so the listing can still be shown while the fit card is skipped. |
| create_fit_card | Outfit input is missing or incomplete | The tool guards first, so an `outfit` that is `None`, empty, or whitespace returns the string "Can't write a fit card without an outfit suggestion" rather than raising; in normal flow this can't happen because the loop only calls it after a successful `suggest_outfit`, and the guard is there for direct or standalone calls, while an LLM exception is caught by the loop, recorded as a friendly `error`, and still leaves the listing and outfit panels populated. |

---

## Architecture

```
  User query + wardrobe choice  (Gradio app.py → handle_query)
        │   query:str, wardrobe:dict
        ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                      PLANNING LOOP  (agent.run_agent)                     │
  │                                                                           │
  │   session = _new_session(query, wardrobe)   ◄──────────┐                  │
  │        │                                               │ read/write      │
  │        ▼                                       ┌────────┴───────────┐     │
  │   [1] parse query                              │   SESSION STATE    │     │
  │        │ writes parsed{description,size,price} │  query             │     │
  │        │ empty desc? ─► [ERROR] ──────────────►│  parsed            │     │
  │        ▼                                       │  search_results    │     │
  │   [2] search_listings(description,size,price)  │  selected_item     │     │
  │        │            (local filter+rank, no LLM)│  wardrobe          │     │
  │        │ results=[] ─► [ERROR] "no match…" ───►│  outfit_suggestion │     │
  │        │                                       │  fit_card          │     │
  │        │ results=[item,…]                      │  error             │     │
  │        ▼                                       └────────┬───────────┘     │
  │   [3] selected_item = results[0] ─────────────────────►│                  │
  │        │                                               │                  │
  │        ▼                                               │                  │
  │   [4] suggest_outfit(selected_item, wardrobe)  ──LLM──►│                  │
  │        │   empty wardrobe → general advice (NOT error) │                  │
  │        │   LLM raises ─► [ERROR] (keep listing) ──────►│                  │
  │        │ writes outfit_suggestion                      │                  │
  │        ▼                                               │                  │
  │   [5] create_fit_card(outfit_suggestion, selected_item)─LLM─►│            │
  │        │   empty outfit → guard string                 │                  │
  │        │ writes fit_card                               │                  │
  │        ▼                                               │                  │
  │   [6] return session ◄─────────── all error branches return here ─────────┤
  └─────────────────────────────────────────────────────────────────────────┘
        │  session dict
        ▼
  handle_query: error set? ─► panel1 = error, panel2/3 = ""
                else        ─► panel1 = listing, panel2 = outfit, panel3 = fit_card
        │
        ▼
  Gradio UI: 🛍️ listing  |  👗 outfit  |  ✨ fit card
```

**Legend:** the `[ERROR]` branches each set `session["error"]` and jump straight to step [6] to return, the LLM-backed tools are `suggest_outfit` and `create_fit_card` while `search_listings` is pure local code, and the session dict is the only shared state, read and written by every step.

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

I'll use Claude (Claude Code) for all three tools, taking them one at a time so I can test each before moving on. For `search_listings` I'll hand it the Tool 1 block above (inputs, return shape, empty-list behavior) along with the docstring TODO in `tools.py` and the field list from `utils/data_loader.py`, expecting a pure-Python implementation that loads with `load_listings()`, applies the `max_price` and case-insensitive substring `size` filters, scores each survivor by keyword overlap across title/description/style_tags/category/colors, drops score-0 items, and returns the sorted dicts; before trusting it I'll read the code to confirm all three params are applied, that `size=None`/`max_price=None` skip their filters, and that no match returns `[]` rather than raising, then run three queries — `"vintage graphic tee", max_price=30` (expecting tees like lst_006/lst_033), `"track jacket", size="M"` (expecting lst_004), and `"designer ballgown", max_price=5` (expecting `[]`). For `suggest_outfit` I'll give it the Tool 2 block plus the empty-wardrobe rule from the error-handling section and expect a function with two prompt branches (populated vs empty wardrobe) that formats wardrobe items by name and always returns a non-empty string, which I'll verify by running it once with `get_example_wardrobe()` (checking it names real pieces like the baggy jeans and chunky white sneakers) and once with `get_empty_wardrobe()` (checking it gives general advice, never names fake items, and never returns `""`). For `create_fit_card` I'll give it the Tool 3 block plus the caption style rules and expect a guard for an empty `outfit` followed by a higher-temperature LLM call that produces a 2–4 sentence caption naming the item, price, and platform once each, which I'll verify by calling it with a real outfit string (checking the casual tone and that price and platform appear) and with `outfit=""` (checking it returns the guard string rather than raising).

**Milestone 4 — Planning loop and state management:**

I'll give Claude the Planning Loop, State Management, Architecture diagram, and Error Handling sections above together with the `run_agent`/`_new_session` skeleton in `agent.py`, expecting `run_agent` to implement the pipeline exactly — parsing the query into `session["parsed"]`, taking the empty-results early return, selecting the top result, wrapping the two LLM tool calls in `try/except`, and returning a populated session; before trusting it I'll trace the generated branches against my diagram to confirm the empty-results path returns before `suggest_outfit`, that an empty wardrobe does not set `error`, and that every early exit sets `session["error"]`, then run `python agent.py` to confirm the happy path fills all three fields and the `"designer ballgown size XXS under $5"` path sets a helpful error with the other fields left `None`. Finally I'll wire up `app.py`'s `handle_query` (handing Claude the Tool and Planning sections again) and click through the example queries in the Gradio UI.

---

## A Complete Interaction (Step by Step)

**What FitFindr does (in my own words):**
FitFindr is a thrift-shopping assistant that finds matching secondhand listings and styles the best one against the user's existing wardrobe, addtionally writing a description of it as well. The user sends a message that triggers `search_listings` (filtering listings by description, size, and max price); if that returns at least one match, the top result feeds `suggest_outfit`, which pairs it with wardrobe items, and that suggestion feeds `create_fit_card`, which produces a short social caption. On failure it stops early instead of passing empty data forward: if `search_listings` finds nothing it tells the user how to adjust their query and halts (never calling `suggest_outfit`), and if the wardrobe is empty `suggest_outfit` can't style the item, so the agent surfaces the found listing on its own.

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 0 — Init & parse.** `run_agent` builds a fresh session. The parse step extracts from the query: `description="vintage graphic tee"`, `size=None` (no size stated), `max_price=30.0` (from "under $30"). These are stored in `session["parsed"]`. (The "baggy jeans / chunky sneakers" detail isn't a filter — it's already represented in the example wardrobe.)

**Step 1 — search_listings.** Called as `search_listings("vintage graphic tee", size=None, max_price=30.0)`. It filters out anything over $30, scores the rest by keyword overlap, drops score-0 items, and returns relevant tees sorted best-first — e.g. `lst_006` ("Graphic Tee — 2003 Tour Bootleg Style", $24, depop, tags include *graphic tee/vintage/band tee*) and `lst_033` ("Vintage Band Tee — Faded Grey", $19, depop). Stored in `session["search_results"]`. List is non-empty → proceed.

**Step 2 — select.** `session["selected_item"] = search_results[0]` → the top-scored tee (say `lst_006`, "Graphic Tee — 2003 Tour Bootleg Style", $24, depop).

**Step 3 — suggest_outfit.** Called as `suggest_outfit(selected_item, wardrobe)` with the example wardrobe. The LLM returns something like: *"Wear it with your baggy dark-wash jeans and chunky white sneakers for an easy streetwear look, then throw the vintage black denim jacket over top. Tuck the front hem slightly so the baggy fit reads intentional."* Stored in `session["outfit_suggestion"]`.

**Step 4 — create_fit_card.** Called as `create_fit_card(outfit_suggestion, selected_item)`. The LLM (higher temp) returns a caption like: *"found this 2003 bootleg tour tee on depop for $24 and it's already my whole personality 🖤 styled it with baggy denim + chunky sneaks. thrift wins only."* Stored in `session["fit_card"]`.

**Step 5 — return.** All three output fields are set and `error is None`; the session is returned.

**Final output to user:** The Gradio UI shows three panels — **🛍️ Top listing found:** the formatted listing (title, $24, depop, condition, size); **👗 Outfit idea:** the styling text from Step 3; **✨ Your fit card:** the caption from Step 4.

**Contrast — no-results path** (e.g. `"designer ballgown size XXS under $5"`): Step 1 returns `[]`, so the loop sets `session["error"]` to a helpful message ("I couldn't find a 'designer ballgown' in size XXS under $5. Try a higher budget or broader keywords…") and returns immediately. `suggest_outfit` and `create_fit_card` are never called; the UI shows the error in panel 1 and leaves panels 2 and 3 blank.
