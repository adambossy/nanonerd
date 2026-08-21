"""Extractor-agnostic judge for how faithfully an article was extracted.

The judge takes whatever raw source HTML and extracted HTML exist for an
article and renders a verdict.  Deterministic signals do the work; an
ambiguous score escalates to a small Claude model when a client is supplied.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import json
import logging
import re
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from anthropic import Anthropic
from lxml import html as lxml_html

from nanonerd.reader.categorize import strip_code_fences

logger = logging.getLogger(__name__)

FidelityStatus = Literal["ok", "degraded", "not_article", "blocked"]
SignalValue = float | int | str | bool

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 256

#: Below this score the deterministic layer calls the extraction degraded.
DEGRADED_BELOW = 0.72
#: Scores inside this band straddle the decision boundary and go to the LLM.
AMBIGUOUS_BAND = (0.35, 0.75)
#: The LLM only overrides the deterministic status when it is this sure.
LLM_MIN_CONFIDENCE = 0.6

_BLOCKED_STATUS_CODES = frozenset({401, 402, 403, 407, 429, 451, 503})

_BOT_WALL_STRONG = (
    "captcha-delivery.com",
    "datadome",
    "cf-browser-verification",
    "/cdn-cgi/challenge-platform",
    "_incapsula_resource",
    "px-captcha",
    "please enable js and disable any ad blocker",
    "enable javascript and cookies to continue",
    "checking your browser before accessing",
    "attention required! | cloudflare",
    "verify you are human",
    "access to this page has been denied",
    "you have been blocked",
    "unusual traffic from your computer network",
)
_BOT_WALL_WEAK = (
    "recaptcha",
    "hcaptcha",
    "are you a robot",
    "please enable javascript",
    "sign in to continue",
    "log in to continue",
)
#: A weak bot-wall marker only counts on a page with almost no prose.
_BOT_WALL_WEAK_MAX_WORDS = 250
#: Shorter than this and something was almost certainly lost, source or no source.
_MIN_ARTICLE_WORDS = 120

_PAYWALL_STRONG = (
    re.compile(r"data-testid=[\"']paywall"),
    re.compile(r"data-component-name=[\"']paywall", re.I),
    re.compile(r"(?:class|id)=[\"'][^\"']*\bpaywall\b", re.I),
    re.compile(r"this (?:post|article|story) is for paid subscribers", re.I),
    re.compile(r"subscribe to (?:continue|keep) reading", re.I),
    re.compile(r"to continue reading[,.]?\s*(?:please\s*)?subscribe", re.I),
)
_PAYWALL_WEAK = (
    re.compile(r"(?:class|id)=[\"'][^\"']*\b(?:meter|metered|regwall)\b", re.I),
    re.compile(r"already a (?:paid )?subscriber", re.I),
)

_NON_ARTICLE_OG_TYPES = frozenset(
    {
        "product",
        "product.group",
        "product.item",
        "video.other",
        "video.movie",
        "video.episode",
        "music.song",
        "music.album",
        "profile",
    }
)
_NON_ARTICLE_SCHEMA_TYPES = frozenset(
    {
        "ProductGroup",
        "Product",
        "CollectionPage",
        "SearchResultsPage",
        "ProfilePage",
        "VideoObject",
        "OfferCatalog",
        "Store",
    }
)
_ARTICLE_SCHEMA_TYPES = frozenset(
    {
        "Article",
        "NewsArticle",
        "BlogPosting",
        "TechArticle",
        "ScholarlyArticle",
        "Report",
        "LiveBlogPosting",
    }
)

_NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "form",
    "button",
    "select",
    "textarea",
    "link",
    "meta",
)
_CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})
_CHROME_MARKER_RE = re.compile(
    r"comment|sidebar|related|site-nav|menu|footer|header|promo|advert|newsletter"
    r"|subscribe|share|social|breadcrumb|pagination|cookie|banner|masthead|popup",
    re.I,
)
#: Never strip a "chrome" element that holds this much of the region's text.
_CHROME_KEEP_SHARE = 0.35
#: A semantic region must hold this much of the body text to be trusted.
_REGION_MIN_SHARE = 0.25

_COUNTED_TAGS = (
    "p",
    "img",
    "figure",
    "figcaption",
    "pre",
    "code",
    "table",
    "video",
    "audio",
    "li",
    "blockquote",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
)

_PROMPT_TEMPLATE = """You are auditing how faithfully a read-later app \
extracted an article from a web page. The reader is used offline on a phone, \
so the user cannot fall back to the source page.

URL: {url}
Title: {title}
Deterministic verdict: {status} (fidelity score {score:.2f})
Deterministic reasons: {reasons}

Measured signals (JSON):
{signals}

Start of the extracted text:
{extracted_head}

End of the extracted text:
{extracted_tail}

Start of the source page's article region:
{source_head}

Pick the status that best describes the extraction:
- "ok": the reader has essentially the whole article.
- "degraded": the article was extracted but meaningful content is missing \
(text, headings, figures, code, math, media) or it is truncated at a paywall.
- "not_article": the page is not an article at all (shop grid, home page, \
search results, video page).
- "blocked": the fetch got a bot wall, captcha, login wall or error page \
instead of the page.

Respond with ONLY JSON: \
{{"status": "...", "confidence": 0.0-1.0, "reason": "<one short sentence>"}}"""


@dataclass(frozen=True, slots=True)
class Verdict:
    status: FidelityStatus
    score: float
    reasons: list[str]
    signals: dict[str, SignalValue]


@dataclass(frozen=True, slots=True)
class _Penalty:
    weight: float
    reason: str


def _words(element: Any) -> int:
    return len(element.text_content().split())


def _text(element: Any) -> str:
    return " ".join(element.text_content().split())


def _drop(element: Any) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _strip_noise(root: Any) -> None:
    for tag in _NOISE_TAGS:
        for element in root.xpath(f"//{tag}"):
            _drop(element)


def _strip_chrome(region: Any) -> None:
    """Remove nav/header/footer-ish elements that do not hold the body text."""
    keep_above = _CHROME_KEEP_SHARE * _words(region)
    for element in list(region.iter()):
        if element is region or not isinstance(element.tag, str):
            continue
        marker = f"{element.get('class') or ''} {element.get('id') or ''}"
        is_chrome = element.tag in _CHROME_TAGS or bool(
            marker.strip() and _CHROME_MARKER_RE.search(marker)
        )
        if is_chrome and _words(element) < keep_above:
            _drop(element)


def _select_region(doc: Any) -> tuple[Any, str]:
    """Best-effort source article region, preferring semantic containers."""
    body = doc.find("body")
    root = body if body is not None else doc
    base_words = _words(root)
    best: Any | None = None
    best_words = 0
    best_label = "body"
    for xpath, label in (
        ("//article", "article"),
        ("//*[@role='main']", "role=main"),
        ("//main", "main"),
    ):
        for candidate in root.xpath(xpath):
            candidate_words = _words(candidate)
            if candidate_words > best_words:
                best, best_words, best_label = candidate, candidate_words, label
    if best is not None and best_words >= _REGION_MIN_SHARE * max(base_words, 1):
        region, label = best, best_label
    else:
        region, label = root, "body"
    _strip_chrome(region)
    return region, label


def _math_blocks(element: Any) -> int:
    raw = str(lxml_html.tostring(element, encoding="unicode"))
    lowered = raw.lower()
    return int(
        len(element.xpath(".//math"))
        + lowered.count("katex-display")
        + lowered.count("mathjax_display")
        + lowered.count('class="math display"')
        + raw.count("$$") // 2
    )


def _element_counts(element: Any) -> dict[str, int]:
    counts = {tag: len(element.xpath(f".//{tag}")) for tag in _COUNTED_TAGS}
    counts["headings"] = sum(counts[f"h{level}"] for level in range(1, 7))
    counts["code_blocks"] = counts["pre"] + counts["code"]
    counts["media_av"] = counts["video"] + counts["audio"]
    counts["math"] = _math_blocks(element)
    counts["link_words"] = sum(_words(anchor) for anchor in element.xpath(".//a"))
    return counts


def _parse_source(source_html: str) -> Any | None:
    try:
        doc = lxml_html.fromstring(source_html)
    except (ValueError, SyntaxError):
        return None
    return doc


def _parse_fragment(content_html: str) -> Any | None:
    try:
        return lxml_html.fragment_fromstring(content_html, create_parent="div")
    except (ValueError, SyntaxError):
        return None


def _og_type(source_html: str) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:type[\"'][^>]+content=[\"']([^\"']+)",
        source_html,
        re.I,
    )
    return match.group(1).strip().lower() if match else ""


def _schema_types(source_html: str) -> list[str]:
    return sorted(set(re.findall(r'"@type"\s*:\s*"([^"]+)"', source_html)))


def _first_match(haystack: str, needles: Sequence[str]) -> str:
    for needle in needles:
        if needle in haystack:
            return needle
    return ""


def _first_pattern(haystack: str, patterns: Sequence[re.Pattern[str]]) -> str:
    for pattern in patterns:
        found = pattern.search(haystack)
        if found is not None:
            return found.group(0)[:60]
    return ""


def _paywall_element(region: Any) -> Any | None:
    matches = region.xpath(
        ".//*[contains(translate(@class,'PAYWL','paywl'),'paywall')"
        " or contains(translate(@data-testid,'PAYWL','paywl'),'paywall')]"
    )
    return matches[0] if matches else None


def _words_before(region: Any, marker: Any) -> int:
    total = 0
    for node in region.iter():
        if node is marker:
            break
        if isinstance(node.tag, str):
            total += len((node.text or "").split())
        total += len((node.tail or "").split())
    return total


def _chunk_signals(chunks: Sequence[tuple[str, int]]) -> dict[str, SignalValue]:
    word_counts = [count for _html, count in chunks]
    total = sum(word_counts)
    return {
        "chunk_count": len(chunks),
        "chunk_words_total": total,
        "max_chunk_share": round(max(word_counts) / total, 3) if total else 0.0,
        "tiny_chunk_share": round(
            sum(1 for count in word_counts if count < 3) / len(word_counts), 3
        ),
    }


def collect_signals(
    *,
    url: str,
    http_status: int | None,
    source_html: str | None,
    extracted_html: str | None,
    chunks: Sequence[tuple[str, int]] | None,
    title: str | None,
) -> dict[str, SignalValue]:
    """Cheap, deterministic measurements of the source/extraction pair."""
    signals: dict[str, SignalValue] = {
        "url_host": urlsplit(url).hostname or "",
        "http_status": http_status if http_status is not None else 0,
        "title_present": bool(title and title.strip()),
        "source_bytes": len(source_html or ""),
        "extracted_bytes": len(extracted_html or ""),
    }

    source_counts: dict[str, int] = {}
    if source_html:
        lowered = source_html.lower()
        signals["bot_wall_strong"] = _first_match(lowered, _BOT_WALL_STRONG)
        signals["bot_wall_weak"] = _first_match(lowered, _BOT_WALL_WEAK)
        signals["paywall_strong"] = _first_pattern(source_html, _PAYWALL_STRONG)
        signals["paywall_weak"] = _first_pattern(source_html, _PAYWALL_WEAK)
        signals["og_type"] = _og_type(source_html)
        schema_types = _schema_types(source_html)
        signals["schema_types"] = ",".join(schema_types[:8])
        signals["schema_article"] = bool(
            _ARTICLE_SCHEMA_TYPES.intersection(schema_types)
        )
        signals["schema_non_article"] = bool(
            _NON_ARTICLE_SCHEMA_TYPES.intersection(schema_types)
        )
        doc = _parse_source(source_html)
        if doc is not None:
            signals["has_article_tag"] = bool(doc.xpath("//article"))
            _strip_noise(doc)
            region, label = _select_region(doc)
            source_counts = _element_counts(region)
            region_words = _words(region)
            signals["source_region"] = label
            signals["source_region_words"] = region_words
            signals["source_p_count"] = source_counts["p"]
            signals["source_link_density"] = (
                round(source_counts["link_words"] / region_words, 3)
                if region_words
                else 0.0
            )
            signals["source_words_per_kb"] = round(
                region_words / max(len(source_html) / 1024, 1), 2
            )
            for key in ("img", "figure", "headings", "code_blocks", "table", "math"):
                signals[f"source_{key}"] = source_counts[key]
            signals["source_media_av"] = source_counts["media_av"]
            signals["source_head_text"] = _text(region)[:600]
            marker = _paywall_element(region)
            signals["paywall_words_before"] = (
                _words_before(region, marker) if marker is not None else 0
            )

    extracted_counts: dict[str, int] = {}
    if extracted_html and extracted_html.strip():
        fragment = _parse_fragment(extracted_html)
        if fragment is not None:
            extracted_counts = _element_counts(fragment)
            extracted_text = _text(fragment)
            signals["extracted_words"] = len(extracted_text.split())
            signals["extracted_head_text"] = extracted_text[:600]
            signals["extracted_tail_text"] = extracted_text[-600:]
            for key in ("img", "figure", "headings", "code_blocks", "table", "math"):
                signals[f"extracted_{key}"] = extracted_counts[key]
            signals["extracted_media_av"] = extracted_counts["media_av"]
    signals.setdefault("extracted_words", 0)

    region_words = int(signals.get("source_region_words", 0))
    extracted_words = int(signals["extracted_words"])
    if region_words >= 150 and extracted_words:
        signals["word_ratio"] = round(extracted_words / region_words, 3)
    if source_counts and extracted_counts:
        for key in ("img", "figure", "headings", "code_blocks", "table", "math"):
            signals[f"missing_{key}"] = max(
                0, source_counts[key] - extracted_counts[key]
            )
        signals["missing_media_av"] = max(
            0, source_counts["media_av"] - extracted_counts["media_av"]
        )

    if chunks is not None and chunks:
        signals.update(_chunk_signals(chunks))
        chunk_total = int(signals["chunk_words_total"])
        if extracted_words:
            signals["chunk_word_ratio"] = round(chunk_total / extracted_words, 3)

    paywall_before = int(signals.get("paywall_words_before", 0))
    if paywall_before and extracted_words:
        signals["extracted_ends_at_paywall"] = (
            0.8 <= extracted_words / paywall_before <= 1.25
        )
    return signals


def _blocked_reason(signals: dict[str, SignalValue]) -> str:
    status = int(signals["http_status"])
    if status in _BLOCKED_STATUS_CODES:
        return f"fetch returned HTTP {status} — the page was not served"
    strong = str(signals.get("bot_wall_strong", ""))
    if strong:
        return f"source page is a bot wall or captcha challenge ({strong})"
    weak = str(signals.get("bot_wall_weak", ""))
    if weak:
        return f"source page has almost no text and a bot wall marker ({weak})"
    return ""


def _is_blocked(signals: dict[str, SignalValue]) -> bool:
    if int(signals["http_status"]) in _BLOCKED_STATUS_CODES:
        return True
    if signals.get("bot_wall_strong"):
        return True
    region_words = int(signals.get("source_region_words", 0))
    return bool(
        signals.get("bot_wall_weak") and region_words < _BOT_WALL_WEAK_MAX_WORDS
    )


def _not_article_reason(signals: dict[str, SignalValue]) -> str:
    og_type = str(signals.get("og_type", ""))
    if og_type in _NON_ARTICLE_OG_TYPES:
        return f"page is not an article (og:type={og_type})"
    if (
        signals.get("schema_non_article")
        and not signals.get("schema_article")
        and int(signals.get("source_p_count", 0)) < 3
    ):
        types = str(signals.get("schema_types", ""))
        return f"page markup describes a non-article page (schema.org {types})"
    p_count = int(signals.get("source_p_count", 0))
    region_words = int(signals.get("source_region_words", 0))
    link_density = float(signals.get("source_link_density", 0.0))
    if p_count == 0 and region_words < 400 and link_density > 0.35:
        return (
            f"source page has no paragraphs and {link_density:.0%} link density — "
            "looks like an index or grid page, not an article"
        )
    if link_density > 0.6 and p_count < 5 and region_words < 1200:
        return (
            f"source page is mostly links ({link_density:.0%} link density) — "
            "looks like a navigation or listing page"
        )
    return ""


def _text_loss_penalty(signals: dict[str, SignalValue]) -> _Penalty | None:
    if "word_ratio" not in signals:
        return None
    ratio = float(signals["word_ratio"])
    reason = f"extraction kept only {ratio:.0%} of the source article text"
    # Losing a fifth of an article is enough on its own: a dropped outro or a
    # sources section is exactly what you notice once you are already reading.
    if ratio < 0.5:
        return _Penalty(0.55, reason)
    if ratio < 0.7:
        return _Penalty(0.40, reason)
    if ratio < 0.8:
        return _Penalty(0.30, reason)
    if ratio < 0.9:
        return _Penalty(0.15, reason)
    return None


def _chunk_penalties(signals: dict[str, SignalValue]) -> list[_Penalty]:
    penalties: list[_Penalty] = []
    extracted_words = int(signals["extracted_words"])
    if "chunk_word_ratio" in signals:
        ratio = float(signals["chunk_word_ratio"])
        if ratio < 0.9:
            reason = (
                f"chunk word counts cover only {ratio:.0%} of the extracted text — "
                "reading progress will be wrong"
            )
            penalties.append(_Penalty(0.5 if ratio < 0.5 else 0.15, reason))
    max_share = float(signals.get("max_chunk_share", 0.0))
    if max_share > 0.6 and extracted_words > 400:
        chunk_count = int(signals.get("chunk_count", 0))
        reason = (
            "the whole article landed in a single chunk"
            if chunk_count == 1
            else f"one chunk holds {max_share:.0%} of the article"
        )
        penalties.append(_Penalty(0.4, reason))
    tiny_share = float(signals.get("tiny_chunk_share", 0.0))
    if tiny_share > 0.5:
        penalties.append(
            _Penalty(0.2, f"{tiny_share:.0%} of chunks are empty or near-empty")
        )
    return penalties


def _structure_penalties(signals: dict[str, SignalValue]) -> list[_Penalty]:
    penalties: list[_Penalty] = []
    source_headings = int(signals.get("source_headings", 0))
    extracted_headings = int(signals.get("extracted_headings", 0))
    if source_headings >= 5:
        if extracted_headings == 0:
            penalties.append(
                _Penalty(0.4, f"all {source_headings} headings were dropped")
            )
        elif extracted_headings < 0.4 * source_headings:
            missing = source_headings - extracted_headings
            penalties.append(_Penalty(0.2, f"{missing} of the headings are missing"))
    source_code = int(signals.get("source_code_blocks", 0))
    extracted_code = int(signals.get("extracted_code_blocks", 0))
    if source_code >= 5 and extracted_code < 0.5 * source_code:
        penalties.append(
            _Penalty(0.2, f"{source_code - extracted_code} code blocks are missing")
        )
    source_tables = int(signals.get("source_table", 0))
    extracted_tables = int(signals.get("extracted_table", 0))
    if source_tables >= 2 and extracted_tables < 0.6 * source_tables:
        penalties.append(
            _Penalty(0.15, f"{source_tables - extracted_tables} tables are missing")
        )
    if (
        int(signals.get("source_math", 0)) >= 3
        and int(signals.get("extracted_math", 0)) == 0
    ):
        penalties.append(
            _Penalty(
                0.25, f"{signals['source_math']} math blocks were lost in extraction"
            )
        )
    return penalties


def _media_penalties(signals: dict[str, SignalValue]) -> list[_Penalty]:
    penalties: list[_Penalty] = []
    missing_images = int(signals.get("missing_img", 0))
    if missing_images >= 2:
        weight = min(0.18, 0.03 * missing_images)
        penalties.append(
            _Penalty(weight, f"{missing_images} images were not extracted")
        )
    missing_figures = int(signals.get("missing_figure", 0))
    if missing_figures >= 3:
        penalties.append(
            _Penalty(0.2, f"{missing_figures} figures and their captions are missing")
        )
    missing_av = int(signals.get("missing_media_av", 0))
    if missing_av >= 2:
        penalties.append(
            _Penalty(0.3, f"{missing_av} video or audio embeds are missing")
        )
    elif missing_av == 1:
        penalties.append(_Penalty(0.1, "a video or audio embed is missing"))
    return penalties


def _paywall_penalty(signals: dict[str, SignalValue]) -> _Penalty | None:
    strong = str(signals.get("paywall_strong", ""))
    weak = str(signals.get("paywall_weak", ""))
    ratio = float(signals.get("word_ratio", 1.0))
    if not strong and not (weak and ratio < 0.75):
        return None
    if signals.get("extracted_ends_at_paywall"):
        return _Penalty(
            0.55,
            "the article is cut off at a paywall — only the free preview was extracted",
        )
    return _Penalty(0.45, "the source page is paywalled — content may be missing")


def _collect_penalties(signals: dict[str, SignalValue]) -> list[_Penalty]:
    penalties: list[_Penalty] = []
    text_loss = _text_loss_penalty(signals)
    if text_loss is not None:
        penalties.append(text_loss)
    penalties.extend(_chunk_penalties(signals))
    penalties.extend(_structure_penalties(signals))
    penalties.extend(_media_penalties(signals))
    paywall = _paywall_penalty(signals)
    if paywall is not None:
        penalties.append(paywall)
    extracted_words = int(signals["extracted_words"])
    if extracted_words < _MIN_ARTICLE_WORDS:
        penalties.append(_Penalty(0.4, f"only {extracted_words} words were extracted"))
    if not signals["title_present"]:
        penalties.append(_Penalty(0.1, "no title was extracted"))
    return penalties


def judge_signals(signals: dict[str, SignalValue]) -> Verdict:
    """Rule layer: turn measured signals into a verdict without any LLM call."""
    if _is_blocked(signals):
        return Verdict("blocked", 0.0, [_blocked_reason(signals)], signals)
    not_article = _not_article_reason(signals)
    if not_article:
        return Verdict("not_article", 0.05, [not_article], signals)
    if not int(signals["extracted_words"]):
        return Verdict("degraded", 0.0, ["no content was extracted"], signals)

    penalties = sorted(
        _collect_penalties(signals), key=lambda item: item.weight, reverse=True
    )
    score = round(max(0.0, 1.0 - sum(item.weight for item in penalties)), 3)
    status: FidelityStatus = "degraded" if score < DEGRADED_BELOW else "ok"
    return Verdict(status, score, [item.reason for item in penalties], signals)


def _prompt_signals(signals: dict[str, SignalValue]) -> str:
    compact = {
        key: value
        for key, value in signals.items()
        if not key.endswith("_text") and key != "schema_types"
    }
    return json.dumps(compact, sort_keys=True)


def _ask_llm(
    *, url: str, title: str | None, verdict: Verdict, client: Anthropic
) -> tuple[dict[str, Any], int, int]:
    signals = verdict.signals
    prompt = _PROMPT_TEMPLATE.format(
        url=url,
        title=title or "(none)",
        status=verdict.status,
        score=verdict.score,
        reasons="; ".join(verdict.reasons) or "(none)",
        signals=_prompt_signals(signals),
        extracted_head=signals.get("extracted_head_text", "(empty)"),
        extracted_tail=signals.get("extracted_tail_text", "(empty)"),
        source_head=signals.get("source_head_text", "(unavailable)"),
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    parsed = json.loads(strip_code_fences(raw))
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object from the judge, got: {raw!r}")
    return (
        cast(dict[str, Any], parsed),
        int(response.usage.input_tokens),
        int(response.usage.output_tokens),
    )


def _apply_llm(
    *, url: str, title: str | None, verdict: Verdict, client: Anthropic
) -> Verdict:
    signals = verdict.signals
    try:
        parsed, input_tokens, output_tokens = _ask_llm(
            url=url, title=title, verdict=verdict, client=client
        )
    except Exception:  # noqa: BLE001 - the judge must never break the pipeline
        logger.warning("fidelity LLM escalation failed for %s", url, exc_info=True)
        signals["llm_used"] = False
        signals["llm_skipped"] = "error"
        return verdict

    status = str(parsed.get("status", "")).strip()
    confidence = float(parsed.get("confidence", 0.0) or 0.0)
    reason = str(parsed.get("reason", "")).strip()
    signals["llm_used"] = True
    signals["llm_skipped"] = ""
    signals["llm_status"] = status
    signals["llm_confidence"] = round(confidence, 3)
    signals["llm_input_tokens"] = input_tokens
    signals["llm_output_tokens"] = output_tokens
    logger.info(
        "fidelity llm judged %s as %s (%s in / %s out tokens)",
        url,
        status,
        input_tokens,
        output_tokens,
    )

    valid = status in ("ok", "degraded", "not_article", "blocked")
    if not valid or confidence < LLM_MIN_CONFIDENCE:
        return verdict
    reasons = list(verdict.reasons)
    if reason and status != "ok":
        reasons.insert(0, reason)
    elif status == "ok":
        reasons = [f"reviewed: {reason}"] if reason else []
    return Verdict(cast(FidelityStatus, status), verdict.score, reasons, signals)


def judge_extraction(
    *,
    url: str,
    http_status: int | None = None,
    source_html: str | None = None,
    extracted_html: str | None = None,
    chunks: Sequence[tuple[str, int]] | None = None,
    title: str | None = None,
    client: Anthropic | None = None,
    use_llm: bool = True,
) -> Verdict:
    """Judge how faithfully `extracted_html` represents `source_html`."""
    signals = collect_signals(
        url=url,
        http_status=http_status,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks,
        title=title,
    )
    verdict = judge_signals(signals)
    signals["llm_used"] = False
    low, high = AMBIGUOUS_BAND
    if not use_llm:
        signals["llm_skipped"] = "disabled"
        return verdict
    if client is None:
        signals["llm_skipped"] = "no client"
        return verdict
    if not low <= verdict.score <= high:
        signals["llm_skipped"] = "score is decisive"
        return verdict
    return _apply_llm(url=url, title=title, verdict=verdict, client=client)
