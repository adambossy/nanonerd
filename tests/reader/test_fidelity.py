import json
from types import SimpleNamespace
from typing import Any

from nanonerd.reader.fidelity import Verdict, judge_extraction

PARAGRAPH = " ".join(f"word{i}" for i in range(60))


def build_source(
    *,
    paragraphs: int = 20,
    head: str = "",
    body_extra: str = "",
    region_tag: str = "article",
) -> str:
    blocks = "".join(f"<p>{PARAGRAPH}</p>" for _ in range(paragraphs))
    return (
        f"<html><head>{head}</head><body>"
        f"<nav><a href='/'>home</a><a href='/about'>about</a></nav>"
        f"<{region_tag}>{blocks}{body_extra}</{region_tag}>"
        f"<footer>copyright</footer></body></html>"
    )


def build_extracted(*, paragraphs: int = 20, extra: str = "") -> str:
    return "".join(f"<p>{PARAGRAPH}</p>" for _ in range(paragraphs)) + extra


def chunks_from(extracted_html: str) -> list[tuple[str, int]]:
    """One chunk per paragraph, word counts matching the text (no tail bug)."""
    parts = [p for p in extracted_html.split("</p>") if "<p>" in p]
    return [(f"{p}</p>", len(p.split(">")[-1].split())) for p in parts]


def create_fake_client(reply: str, calls: list[Any]) -> Any:
    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply)],
            usage=SimpleNamespace(input_tokens=900, output_tokens=40),
        )

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def create_exploding_client() -> Any:
    def create(**kwargs: Any) -> Any:
        raise RuntimeError("no api key")

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def _as_dict(verdict: Verdict, reason_keyword: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {"status": verdict.status}
    if reason_keyword is not None:
        result["reason_found"] = any(
            reason_keyword in reason for reason in verdict.reasons
        )
    return result


def test_judge_extraction_blocked_on_http_status():
    # input
    source_html = "<html><body><p>Forbidden</p></body></html>"

    # act
    output = judge_extraction(
        url="https://www.nytimes.com/story",
        http_status=403,
        source_html=source_html,
        extracted_html=None,
        chunks=None,
        title="",
    )

    # expected
    expected_output = {"status": "blocked", "reason_found": True}

    # assert
    assert _as_dict(output, "HTTP 403") == expected_output


def test_judge_extraction_blocked_on_bot_wall_markers():
    # input
    source_html = (
        "<html><head><title>nytimes.com</title></head><body>"
        "<p id='cmsg'>Please enable JS and disable any ad blocker</p>"
        "<script>var dd={'host':'geo.captcha-delivery.com'}</script>"
        "</body></html>"
    )

    # act
    output = judge_extraction(
        url="https://www.nytimes.com/story",
        http_status=200,
        source_html=source_html,
        extracted_html=None,
        chunks=None,
        title="nytimes.com",
    )

    # expected
    expected_output = {"status": "blocked", "reason_found": True}

    # assert
    assert _as_dict(output, "bot wall") == expected_output


def test_judge_extraction_not_article_on_product_og_type():
    # input
    head = "<meta property='og:type' content='product.group'>"
    source_html = build_source(paragraphs=0, head=head, region_tag="div")

    # act
    output = judge_extraction(
        url="https://shop.example.com/collections/all",
        http_status=200,
        source_html=source_html,
        extracted_html=None,
        chunks=None,
        title="Shop All",
    )

    # expected
    expected_output = {"status": "not_article", "reason_found": True}

    # assert
    assert _as_dict(output, "og:type") == expected_output


def test_judge_extraction_not_article_on_link_grid():
    # input
    cards = "".join(f"<a href='/p/{i}'>Product {i} $99</a>" for i in range(60))
    source_html = (
        f"<html><head></head><body><div class='grid'>{cards}</div></body></html>"
    )

    # act
    output = judge_extraction(
        url="https://shop.example.com/collections/all",
        http_status=200,
        source_html=source_html,
        extracted_html=None,
        chunks=None,
        title="Shop All",
    )

    # expected
    expected_output = {"status": "not_article", "reason_found": True}

    # assert
    assert _as_dict(output, "link density") == expected_output


def test_judge_extraction_ok_on_faithful_extraction():
    # input
    source_html = build_source(paragraphs=20)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "ok", "reasons": [], "score": 1.0}

    # assert
    assert {
        "status": output.status,
        "reasons": output.reasons,
        "score": output.score,
    } == expected_output


def test_judge_extraction_degraded_on_text_loss():
    # input
    source_html = build_source(paragraphs=20)
    extracted_html = build_extracted(paragraphs=6)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "of the source article text") == expected_output


def test_judge_extraction_degraded_on_single_chunk():
    # input
    source_html = build_source(paragraphs=20)
    extracted_html = f"<div>{build_extracted(paragraphs=20)}</div>"

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=[(extracted_html, 1200)],
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "single chunk") == expected_output


def test_judge_extraction_degraded_on_chunk_word_mismatch():
    # input
    source_html = build_source(paragraphs=20)
    extracted_html = build_extracted(paragraphs=20)
    # The tail-text bug: chunk word counts are far below the text they contain.
    broken_chunks = [(html, 1) for html, _ in chunks_from(extracted_html)]

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=broken_chunks,
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "chunk word counts") == expected_output


def test_judge_extraction_degraded_on_dropped_headings():
    # input
    headings = "".join(f"<h2>Section {i}</h2>" for i in range(8))
    source_html = build_source(paragraphs=20, body_extra=headings)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "headings") == expected_output


def test_judge_extraction_degraded_on_paywall_marker():
    # input
    paywall = "<div data-testid='paywall'>This post is for paid subscribers</div>"
    source_html = build_source(paragraphs=20, body_extra=paywall)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.substack.com/p/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "paywall") == expected_output


def test_judge_extraction_degraded_on_missing_figures_and_media():
    # input
    media = (
        "".join(
            f"<figure><img src='/f{i}.png'><figcaption>Fig {i}</figcaption></figure>"
            for i in range(4)
        )
        + "<video src='/a.mp4'></video><audio src='/b.mp3'></audio>"
    )
    source_html = build_source(paragraphs=20, body_extra=media)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "figures") == expected_output


def test_judge_extraction_missing_images_alone_stays_ok():
    # input
    images = "".join(f"<img src='/i{i}.png'>" for i in range(5))
    source_html = build_source(paragraphs=20, body_extra=images)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "ok", "reason_found": True}

    # assert
    assert _as_dict(output, "images") == expected_output


def test_judge_extraction_degraded_on_very_short_extraction():
    # input
    extracted_html = "<p>Ten little words is not much of an article at all.</p>"

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=None,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "words were extracted") == expected_output


def test_judge_extraction_degraded_when_nothing_extracted():
    # input
    source_html = build_source(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html="",
        chunks=[],
        title="A Post",
    )

    # expected
    expected_output = {"status": "degraded", "reason_found": True}

    # assert
    assert _as_dict(output, "no content was extracted") == expected_output


def test_judge_extraction_skips_llm_when_disabled():
    # input
    source_html = build_source(paragraphs=20)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
        use_llm=False,
    )

    # expected
    expected_output = {"llm_used": False, "llm_skipped": "disabled"}

    # assert
    assert {
        "llm_used": output.signals["llm_used"],
        "llm_skipped": output.signals["llm_skipped"],
    } == expected_output


def test_judge_extraction_escalates_to_llm_in_ambiguous_band():
    # input
    calls: list[Any] = []
    reply = json.dumps(
        {"status": "ok", "confidence": 0.9, "reason": "only decorative art missing"}
    )
    client = create_fake_client(reply, calls)
    media = (
        "".join(
            f"<figure><img src='/f{i}.png'><figcaption>Fig {i}</figcaption></figure>"
            for i in range(4)
        )
        + "<video src='/a.mp4'></video><audio src='/b.mp3'></audio>"
    )
    source_html = build_source(paragraphs=20, body_extra=media)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
        client=client,
    )

    # expected
    expected_output = {
        "status": "ok",
        "llm_used": True,
        "model": "claude-haiku-4-5",
        "input_tokens": 900,
    }

    # assert
    assert {
        "status": output.status,
        "llm_used": output.signals["llm_used"],
        "model": calls[0]["model"],
        "input_tokens": output.signals["llm_input_tokens"],
    } == expected_output


def test_judge_extraction_llm_low_confidence_keeps_deterministic_status():
    # input
    calls: list[Any] = []
    reply = json.dumps({"status": "ok", "confidence": 0.2, "reason": "not sure"})
    client = create_fake_client(reply, calls)
    media = (
        "".join(
            f"<figure><img src='/f{i}.png'><figcaption>Fig {i}</figcaption></figure>"
            for i in range(4)
        )
        + "<video src='/a.mp4'></video><audio src='/b.mp3'></audio>"
    )
    source_html = build_source(paragraphs=20, body_extra=media)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
        client=client,
    )

    # expected
    expected_output = {"status": "degraded", "llm_status": "ok"}

    # assert
    assert {
        "status": output.status,
        "llm_status": output.signals["llm_status"],
    } == expected_output


def test_judge_extraction_llm_failure_falls_back_to_deterministic():
    # input
    client = create_exploding_client()
    media = (
        "".join(
            f"<figure><img src='/f{i}.png'><figcaption>Fig {i}</figcaption></figure>"
            for i in range(4)
        )
        + "<video src='/a.mp4'></video><audio src='/b.mp3'></audio>"
    )
    source_html = build_source(paragraphs=20, body_extra=media)
    extracted_html = build_extracted(paragraphs=20)

    # act
    output = judge_extraction(
        url="https://example.com/post",
        http_status=200,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks_from(extracted_html),
        title="A Post",
        client=client,
    )

    # expected
    expected_output = {"status": "degraded", "llm_used": False, "llm_skipped": "error"}

    # assert
    assert {
        "status": output.status,
        "llm_used": output.signals["llm_used"],
        "llm_skipped": output.signals["llm_skipped"],
    } == expected_output
