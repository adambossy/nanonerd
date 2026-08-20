# nano::nerd Reader — Content Fidelity Strategies

**Date:** 2026-08-20
**Status:** Proposal

Strategies for lifting article content in a way that is faithful to the
original design, with three modes always available per article:

1. **Original mode** — the article as its author designed it, minus ads.
2. **Clean mode** — a readable, distraction-free rendering for pages whose
   native design is poor.
3. **Static archive** — a permanent copy that renders identically forever,
   with reading progress and resume position overlaid on it.

## Why the current pipeline mangles articles

The save path is: extension posts `{url, title}` → server fetches with
`httpx` (`extract.py:54`) → `trafilatura.extract(..., output_format="html",
include_images=False, favor_recall=True)` (`extract.py:80`) → chunked one
block element per chunk (`chunking.py:52`) → reader re-renders chunks with
its own CSS.

Running that exact pipeline on a representative rich article (figures with
captions, inline code, a code block, a table, a callout, footnotes, ads, a
sidebar) reproduces every reported symptom:

- **All images, figures, and captions are deleted** (`include_images=False`),
  leaving dangling prose like "The chart above shows…" with no chart above.
- **Inline `<code>` spans are rewritten to `<pre>`** — trafilatura's HTML
  serializer emits `<p>Notice the <pre>promote</pre> call…</p>`, which is
  invalid HTML; the browser's parser then splits the paragraph into three
  fragments. Code blocks come out as nested `<pre><pre>` with the
  `language-*` class stripped, so syntax highlighting is impossible.
- **Non-standard containers are dropped**: callout/aside `<div>`s, bylines,
  and date lines vanish (~50% of the demo page's article words were lost).
- **Footnote structure degrades**: `<ol>` becomes `<ul>`, element `id`s are
  stripped, and in-page `#fn1` links are absolutized to dead URLs.
- **JS-rendered pages save garbage**: a SPA shell extracts to a one-line
  article reading "Please enable JavaScript". Static `httpx` fetch also
  loses anything behind bot checks, cookie walls, or paywalls the user's own
  browser session would pass.
- **Table semantics are thinned** (`thead`/`tbody` stripped) though cell
  content survives.

The root cause is architectural, not a tuning problem: **the server fetches
a different page than the one the user saw** (no JS, no session), and
**trafilatura re-serializes content into its own impoverished tag set**
rather than preserving the author's DOM. Ad removal, notably, already works
well — trafilatura dropped the inline ad, sidebar ads, and newsletter box.

## The architectural move: capture in the browser at save time

The extension already runs in the page with `activeTab` + `scripting`
permissions (`manifest.json:13`). Everything below gets dramatically easier
if saving captures the **rendered DOM the user is looking at** instead of
making the server re-fetch:

- JS-rendered pages, paywalled pages, and bot-blocked pages capture
  perfectly — the user's browser already won those fights.
- The capture *is* the static archive: it renders identically forever, even
  after the original 404s.
- Original design comes for free — it's the author's own CSS.
- The server-side `httpx` path remains as fallback for saves that don't come
  from the extension (iOS Shortcut, context-menu "save link" for pages never
  opened).

All strategies below assume this capture exists; the extraction strategies
then operate on the captured DOM rather than raw fetched HTML.

## Deterministic strategies

### D1. Self-contained DOM snapshot (the static archive + original mode)

At save time a content script serializes the live DOM into one
self-contained HTML file: stylesheets inlined, images/fonts converted to
`data:` URIs, `<script>` removed, hidden nodes and framework debris pruned.
Do not hand-roll this — embed **SingleFile** (MIT, designed to be embedded
in MV3 extensions; also available as `single-file-cli` for the server-side
fallback path via headless Chromium). Store the snapshot alongside
`content_html`:

```
articles.snapshot_html  TEXT      -- gzip'd, or object storage key
articles.snapshot_kind  TEXT      -- 'dom' | 'server' | null
```

The reader serves it in a sandboxed `<iframe sandbox="allow-same-origin">`
with a strict CSP (no scripts, no network) from a dedicated endpoint —
snapshot pages are untrusted third-party markup.

Size note: image-heavy snapshots run 2–20 MB. Gzip in Postgres (`bytea`) is
fine at personal scale on Neon; if it grows, move blobs to Tigris on Fly and
keep only keys in Postgres.

### D2. Ad and annoyance removal via filter lists

Ads are an already-solved deterministic problem: **EasyList + EasyList
Cookie + Fanboy Annoyance** cosmetic rules are machine-readable CSS
selectors maintained daily by the adblock community. Apply them at snapshot
time (delete matching nodes from the capture) or serve time (inject a
generated `display:none` stylesheet into the iframe). Combined with script
stripping from D1 — which alone kills most dynamically injected ads —
this covers ads, cookie banners, newsletter modals, and "related posts"
chum boxes without any model in the loop. Keep a small per-domain override
list for false positives.

### D3. Clean mode extracted from the snapshot, preserving author DOM

Replace "trafilatura re-serialization" with "**subtree selection**": run
**Mozilla Readability** (the Firefox Reader Mode engine) over the captured
DOM. Critically, Readability returns a cleaned *subtree of the original
DOM* — it keeps `<img>`, `<figure>`/`<figcaption>`, `<pre>`/`<code>` with
their classes, `<table>` structure, element `id`s (so footnote jumps keep
working), rather than rewriting tags. Clean mode then applies the reader's
typography to the author's own markup. If trafilatura stays in the stack
for the fallback path, at minimum flip `include_images=True`,
`include_formatting=True`, `include_tables=True` and post-process the
`<p><pre>` inline-code bug — but Readability-on-snapshot should become the
primary clean-mode extractor.

Chunking (`chunk_html`) continues to work unchanged on the result: one
chunk per block element, now including `<figure>` blocks.

### D4. Progress overlay + resume on the original design (text anchors)

Keep the existing chunk model as the single source of truth for progress,
and project it onto the snapshot. For each chunk, store a **text-quote
anchor** computed at extraction time — the approach used by Hypothesis and
the W3C Web Annotation model:

```
chunks.anchor  JSONB  -- { "quote": first+last ~40 chars of normalized text,
                       --   "prefix": ~30 chars before, "suffix": ~30 after }
```

The reader injects a tiny bridge script into the snapshot iframe (same
origin, so no CSP gymnastics): it locates each anchor in the snapshot DOM
via normalized text search with fuzzy fallback, wraps the match's block
ancestor, and reuses the *exact* logic already in `useReadTracking.ts` —
IntersectionObserver, scroll-past-top rule, dwell-time cap — posting read
chunk ids to the parent via `postMessage`. On open, scroll the iframe to
the first unread anchor, exactly mirroring `Reader.tsx:27`.

Because progress lives on chunks, **original mode and clean mode share one
progress state**: read half in the original design, switch to clean mode,
and the resume point carries over. Anchoring is deterministic and
verifiable: any chunk whose anchor fails to locate is logged; if >10% of
anchors miss, fall back to percent-scroll resume for that article.

### D5. Per-article mode default, deterministically scored

A cheap heuristic decides which mode an article opens in by default:
text-to-markup ratio of the snapshot, count of filter-list hits, presence
of fixed/sticky elements, body font size and measure (line length in
characters), contrast. Score above threshold → default to original mode;
below → clean mode. Always a one-tap toggle, and the user's explicit choice
per article is remembered (`articles.preferred_mode`).

## Non-deterministic (LLM) strategies

Medium-quality models (`claude-haiku-4-5` — already the categorization
model — or Sonnet for the hard cases) are used in three safe patterns.
None of them generate article text; they **select, score, and emit rules**
that deterministic code executes, so hallucination cannot corrupt content.

### N1. LLM extraction judge (fidelity triage)

After extraction, give the model the snapshot's text (cheap: text only,
truncated) and the extracted text, and ask for a structured verdict:
missing figures/captions, broken paragraphs, truncation, leftover junk,
plus a "is the native design clean and readable?" judgment to feed D5's
default-mode choice. Articles that fail go to N2 for repair instead of
being served broken. This is also the tool for **auditing the existing
backlog**: run it over every saved article to find the mangled ones worth
reprocessing.

### N2. LLM node selection ("LLM picks, code slices")

For pages where Readability fails (unusual layouts, interleaved junk):
serialize the snapshot DOM to a skeleton — every block element as one line
of `node_id · tag · classes · first ~15 words` — and ask the model to
return JSON: the node ids composing the article, each labeled `title |
byline | body | figure | footnote | junk | ad`. Deterministic code then
slices those exact nodes out of the original DOM, in order. The output is
composed of the author's own nodes, so fidelity is guaranteed; the model
only decided *which* nodes. Wrong selections degrade to "included junk /
missed a paragraph", never to fabricated text, and N1 re-judges the result.

### N3. Per-domain recipes: non-deterministic once, deterministic forever

Saved articles cluster heavily by domain in a personal reader. The first
time N2 runs for a domain, ask the model to also emit a **recipe** — CSS
selectors for content root, junk, and ads on this site. Store it:

```
site_recipes(domain, content_selector, remove_selectors[], created_at, hit_rate)
```

Subsequent saves from that domain apply the recipe with zero model calls;
a deterministic validator (extracted word count vs. snapshot word count,
anchor location success rate) detects when a site redesign breaks the
recipe and re-triggers N2. This converges the system toward deterministic
behavior while keeping the LLM as the recipe author, and the recipes are
inspectable/hand-editable.

### N4. Vision pass for residual ads (optional)

For ads that survive filter lists (native ads, sponsored cards styled like
content): screenshot the snapshot in headless Chromium, ask a vision model
to flag ad-looking regions, map regions back to DOM nodes by coordinates,
and add those selectors to the domain recipe. Worth building only if D2
proves insufficient in practice.

## Backlog migration

For the existing prod articles:

1. Run N1 over all `status='ready'` articles to rank mangling severity.
2. Re-fetch the worst offenders server-side through headless Chromium +
   SingleFile (gets JS rendering; won't get paywalled content).
3. Preserve existing read progress across re-extraction by matching old
   chunk text into the new chunk list (same normalized-text fingerprinting
   as D4) and carrying `read_at` over.
4. Pages that can't be re-fetched cleanly get a "re-save for archive copy"
   badge in the UI; opening the original with the extension offers one-tap
   re-capture.

## Suggested phasing

1. **Phase 1 (foundation):** extension DOM capture via SingleFile +
   snapshot storage + sandboxed original-mode viewing. Immediate wins:
   static archive, JS/paywall pages, original design.
2. **Phase 2 (progress):** chunk text anchors + iframe bridge port of
   `useReadTracking` → tracker and resume on the original design.
3. **Phase 3 (clean mode v2):** Readability-on-snapshot replaces
   trafilatura as primary; images on; D5 default-mode heuristic.
4. **Phase 4 (ads/polish):** EasyList cosmetic filtering; N1 judge in the
   save pipeline; backlog audit + migration.
5. **Phase 5 (long tail):** N2 node selection for pages the judge flags;
   N3 domain recipes.

## Open questions

- Snapshot storage ceiling on Neon free/launch tier — compress in Postgres
  first, measure, move to object storage only if needed?
- iOS Shortcut path can't capture DOM; is server-side headless Chromium
  (Fly machine with Chromium, ~200 MB image) acceptable for that path, or
  do iOS saves stay on the current static-fetch quality?
- Should clean mode inherit the original's fonts/accent colors (a "hybrid"
  mode) — extract `font-family`/accent CSS custom properties from the
  snapshot into the reader theme?
