"""The deterministic judge, measured against real prod extractions.

Fixtures under `tests/fixtures/fidelity/` are gzipped copies of pages that were
actually saved to the reader, paired with the `content_html` the pipeline
stored for them.  `<script>`/`<style>` bodies are stripped to keep the repo
small (except for sample 13, whose bot-wall markers live in inline script).

The extracted HTML is what the pipeline stored *before* the trafilatura
patches landed, so it is a snapshot of a known-bad extractor. The chunk
statistics, however, come from today's `chunk_html`.
"""

import gzip
from pathlib import Path

from nanonerd.reader.chunking import chunk_html
from nanonerd.reader.fidelity import Verdict, judge_extraction

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fidelity"

#: sample id -> (expected status, http status seen when it was fetched)
CORPUS = {
    1: ("ok", 200),  # joelonsoftware, 1425 words, matches the source
    7: ("degraded", 200),  # lilianweng, figures + display math dropped
    9: ("degraded", 200),  # github readme, every heading dropped
    10: ("degraded", 200),  # substack, truncated at the paywall
    13: ("blocked", 403),  # nytimes, DataDome challenge page
    15: ("degraded", 200),  # ordinaryabundance, one 1551-word chunk
    16: ("degraded", 200),  # mintlify docs, tail-text chunking bug
    21: ("ok", 200),  # tullie.ai, all paragraphs present
    23: ("degraded", 200),  # a16z, 17 images and 11 headings missing
    24: ("not_article", 200),  # shopify collection grid
    25: ("degraded", 200),  # simedw, video/audio embeds and figures missing
}


def read_fixture(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8")


def judge_sample(sample_id: int, http_status: int) -> Verdict:
    extracted = read_fixture(f"extracted_{sample_id}.html.gz").strip()
    chunks = [(chunk.html, chunk.word_count) for chunk in chunk_html(extracted)]
    return judge_extraction(
        url=(FIXTURES / f"url_{sample_id}.txt").read_text().strip(),
        http_status=http_status,
        source_html=read_fixture(f"source_{sample_id}.html.gz"),
        extracted_html=extracted,
        chunks=chunks,
        title="Sample title" if extracted else "",
        use_llm=False,
    )


def test_judge_extraction_matches_hand_labelled_corpus():
    # input
    input_samples = dict(CORPUS)

    # act
    output = {
        sample_id: judge_sample(sample_id, http_status).status
        for sample_id, (_expected, http_status) in input_samples.items()
    }

    # expected
    expected_output = {
        sample_id: expected for sample_id, (expected, _status) in input_samples.items()
    }

    # assert
    assert output == expected_output


def test_judge_extraction_detects_bot_wall_without_status_code():
    # input
    sample_id = 13

    # act
    output = judge_sample(sample_id, 200)

    # expected
    expected_output = {"status": "blocked", "marker": "captcha-delivery.com"}

    # assert
    assert {
        "status": output.status,
        "marker": output.signals["bot_wall_strong"],
    } == expected_output


def test_judge_extraction_reports_paywall_truncation_for_substack():
    # input
    sample_id = 10

    # act
    output = judge_sample(sample_id, 200)

    # expected
    expected_output = {"ends_at_paywall": True, "top_reason_mentions_paywall": True}

    # assert
    assert {
        "ends_at_paywall": output.signals["extracted_ends_at_paywall"],
        "top_reason_mentions_paywall": "paywall" in output.reasons[0],
    } == expected_output


def test_judge_extraction_still_flags_samples_whose_chunking_was_fixed():
    """15 and 16 were degraded partly by chunking bugs, since fixed.

    The chunker no longer produces one giant chunk (15) or word counts that
    ignore tail text (16), so both samples now rest on text loss alone: each
    still drops roughly a fifth of the source article. The chunk-shape rules
    stay covered by the synthetic cases in test_fidelity.py.
    """
    # input
    input_samples = [15, 16]

    # act
    output = {
        sample_id: judge_sample(sample_id, 200).status for sample_id in input_samples
    }

    # expected
    expected_output = {15: "degraded", 16: "degraded"}

    # assert
    assert output == expected_output


def test_judge_extraction_no_longer_sees_chunk_defects_after_chunker_fix():
    # input
    input_samples = [15, 16]

    # act
    output = {
        sample_id: {
            "single_chunk": int(judge_sample(sample_id, 200).signals["chunk_count"])
            == 1,
            "word_counts_wrong": float(
                judge_sample(sample_id, 200).signals["chunk_word_ratio"]
            )
            < 0.9,
        }
        for sample_id in input_samples
    }

    # expected
    expected_output = {
        sample_id: {"single_chunk": False, "word_counts_wrong": False}
        for sample_id in input_samples
    }

    # assert
    assert output == expected_output
