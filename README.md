# FitFindr — Starter Kit

This starter kit contains everything you need to begin Project 2.

## What's Included

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py         # Helper functions for loading the data
├── planning.md                # Your planning template — fill this out first
└── requirements.txt           # Python dependencies
```

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## The Mock Listings Dataset

`data/listings.json` contains 40 mock secondhand listings across categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, and more).

Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`.

Load it with:
```python
from utils.data_loader import load_listings
listings = load_listings()
```

## The Wardrobe Schema

`data/wardrobe_schema.json` defines the format your agent uses to represent a user's existing wardrobe. It includes:

- `schema`: field definitions for a wardrobe item
- `example_wardrobe`: a sample wardrobe with 10 items you can use for testing
- `empty_wardrobe`: a starting template for a new user

Load an example wardrobe with:
```python
from utils.data_loader import get_example_wardrobe
wardrobe = get_example_wardrobe()
```

## Where to Start

1. **Read `planning.md` and fill it out before writing any code.**
2. Verify the data loads correctly by running `python utils/data_loader.py`.
3. Build and test each tool individually before connecting them through your planning loop.

Your implementation files go in this same directory. There's no required file structure for your agent code — organize it however makes sense for your design.

---

## Running FitFindr

```bash
python app.py        # Gradio web app — open the URL printed in your terminal
                     # (usually http://localhost:7860, but the port can differ)
python agent.py      # CLI: runs a happy-path query and a no-results query
pytest tests/        # tool tests, incl. one per failure mode
```

## Tool Inventory

All three tools live in `tools.py` and can be called and tested in isolation. The
two LLM-backed tools use Groq's `llama-3.3-70b-versatile`.

### 1. `search_listings(description, size=None, max_price=None) → list[dict]`

- **Inputs:** `description: str` — free-text keywords (e.g. `"vintage graphic tee"`);
  `size: str | None` — optional size, matched case-insensitively as a substring so
  `"M"` also matches `"S/M"`; `max_price: float | None` — inclusive price ceiling.
- **Output:** a `list[dict]` of full listing dicts (`id`, `title`, `description`,
  `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`,
  `platform`), sorted most-relevant first; `[]` if nothing matches.
- **Purpose:** pure local search (no LLM). Filters by price and size, then ranks by
  keyword overlap across title/description/style_tags/category/colors, with a bonus
  for hits in the title or tags. Filler words are ignored so they don't inflate scores.

### 2. `suggest_outfit(new_item, wardrobe) → str`

- **Inputs:** `new_item: dict` — the selected listing; `wardrobe: dict` —
  `{"items": [...]}`, each item having `name`, `category`, `colors`, `style_tags`,
  optional `notes`. May be empty.
- **Output:** a non-empty `str` of styling advice (2–4 sentences).
- **Purpose:** asks the LLM to pair the new item with the user's actual wardrobe
  pieces by name. If the wardrobe is empty it gives **general** advice and avoids
  inventing items the user doesn't own.

### 3. `create_fit_card(outfit, new_item) → str`

- **Inputs:** `outfit: str` — the suggestion from `suggest_outfit`; `new_item: dict`
  — the same listing, for the item name, price, and platform.
- **Output:** a `str` caption (2–4 sentences), casual voice, run at high temperature
  so repeat runs vary.
- **Purpose:** turns the outfit into a shareable OOTD-style caption mentioning the
  item, price, and platform once each.

## Planning Loop

`run_agent(query, wardrobe)` in `agent.py` is a **fixed, linear pipeline with
early-exit branches** — not a "let the LLM pick a tool" loop. The order is always
**parse → search → select → suggest → fit card**, but the agent makes a real
decision at each gate about whether to continue or stop, and it does **not** call
all three tools unconditionally.

1. **Parse.** A fresh session is created and the query is parsed into a
   `description`, optional `size`, and optional `max_price` (regex pulls out phrases
   like `under $30` and `size M` and strips them from the keywords). **Decision:** if
   no description survives, the agent stops and asks what the user wants — it never
   searches on nothing.
2. **Search & branch.** `search_listings` runs. **Decision:** if it returns `[]`, the
   agent sets a specific error and **returns immediately — `suggest_outfit` is never
   called.** This branch is what makes the agent behave differently on a good query
   vs. an impossible one. Otherwise it continues.
3. **Select.** `search_results[0]` is stored as `selected_item` — that exact dict
   flows into the next two tools.
4. **Suggest.** `suggest_outfit` runs inside a `try/except`. **Decision:** an empty
   wardrobe is *not* an error (the tool returns general advice and the loop
   proceeds), but a real LLM failure sets a friendly error and ends the run.
5. **Fit card.** `create_fit_card` runs, also guarded.

The loop finishes when all three outputs are populated **or** any gate sets
`session["error"]`. The caller checks `error` first.

## State Management

All state for one interaction lives in a single **session dict** created by
`_new_session()` in `agent.py`. There is no global state and nothing persists
between calls, so each request is isolated and testable. The tools are stateless —
they take what they need as arguments and return a value the loop writes back into
the session. Data flows in **one direction**, each step reading what the previous
one wrote:

```
parsed → search_results → selected_item → outfit_suggestion → fit_card
```

`error` starts as `None` and short-circuits everything downstream the moment a gate
sets it. The session is the single source of truth; the Gradio UI reads straight
from it. State passing is verifiable: after a run,
`session["selected_item"] is session["search_results"][0]` is `True`, proving the
same object flows through — no re-prompting, no hardcoded hand-offs.

## Error Handling

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | No listing matches | Loop sets a specific error and stops before `suggest_outfit`. |
| `suggest_outfit` | Wardrobe is empty | **Not an error** — returns general styling advice; loop continues. |
| `suggest_outfit` | LLM call raises | Caught by the loop; friendly error set, fit card skipped, listing still shown. |
| `create_fit_card` | Outfit string empty/missing | Tool returns a descriptive message instead of raising. |

**Concrete example from testing** — the impossible query
`"designer ballgown size XXS under $5"`:

```
>>> search_listings('designer ballgown', size='XXS', max_price=5)
[]                                   # empty list, no exception

# full agent on the same query:
error    : I couldn't find "designer ballgown" size XXS under $5. Try broader
           keywords, a higher budget, or dropping the size filter.
fit_card : None                      # suggest_outfit / create_fit_card never ran
```

The response says *what* failed and *what to try* — not just "no results." The
empty-wardrobe and empty-outfit failures were triggered the same way; the full
captured transcript is in `docs/failure_modes_demo.txt`.

## AI Usage

I used **Claude** to help implement the project from the specs in `planning.md`.

**1. Implementing `search_listings`.** *Input:* the Tool 1 spec block (inputs,
return shape, empty-list failure mode) plus the field list from
`utils/data_loader.py`. *Produced:* a function that filters by price and size and
scores listings by keyword overlap. *What I changed:* the first version weighted
every keyword equally, so `"vintage graphic tee"` ranked any item merely tagged
*vintage* as highly as the actual tees. I added a **title/style-tag scoring bonus**
so the genuinely relevant item lands at `[0]` (which the loop depends on) and a
**stopword filter** so filler words don't inflate scores.

**2. Implementing the planning loop (`run_agent`).** *Input:* the Planning Loop and
State Management sections plus the architecture diagram from `planning.md`.
*Produced:* the branching loop with the session dict. *What I reviewed/overrode:* I
verified it **returns early on empty search results before calling `suggest_outfit`**
rather than calling all three tools unconditionally, confirmed an **empty wardrobe is
not treated as an error**, and made sure both LLM calls are wrapped so a network
failure records a friendly `session["error"]` instead of crashing the app.

## Spec Reflection

The implementation follows `planning.md` closely — the planning loop, state dict,
and error branches match the spec and diagram one-to-one. A few honest notes:

- **Query parsing lives inline**, as the spec's "Additional Tools" note anticipated;
  a standalone `parse_query` tool was considered but not needed.
- **The parser can leave a trailing stopword** (e.g. `"90s track jacket in size M"` →
  description `"90s track jacket in"`). This is harmless because `search_listings`
  ignores stopwords, so I left it rather than over-engineer the regex.
- **Search is deliberately broad** (a common keyword like *vintage* matches many
  listings). Because only `search_results[0]` is used and the title/tag bonus floats
  the right item to the top, breadth doesn't affect output, so I kept the ranking as
  specified instead of adding a relevance threshold.

## Demo Video

A 3–5 minute walkthrough showing a complete three-tool interaction, visible state
passing between steps, and a triggered failure with the agent's graceful response.
*https://www.loom.com/share/b084d38af31942759166c2a7542c8f2b*
