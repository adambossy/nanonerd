"""CLI for the extraction-fidelity judge.

    python -m nanonerd.reader.judge --url https://example.com/post
    python -m nanonerd.reader.judge --article 17
    python -m nanonerd.reader.judge --all

`--url` fetches, extracts and judges a page without touching the database.
`--article`/`--all` re-fetch stored articles, judge them against the content
already in the database, and backfill the fidelity columns.
"""

from dataclasses import asdict
import json
from typing import Annotated

from anthropic import Anthropic
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session
import typer

from nanonerd.reader.chunking import chunk_html
from nanonerd.reader.db import SessionLocal
from nanonerd.reader.extract import FetchError, extract_article, fetch_html
from nanonerd.reader.fidelity import Verdict, judge_extraction
from nanonerd.reader.models import Article
from nanonerd.reader.pipeline import apply_verdict, fidelity_client

app = typer.Typer(add_completion=False, help="Judge extraction fidelity.")


def _fetch_source(url: str) -> tuple[str | None, int | None]:
    try:
        return fetch_html(url), 200
    except FetchError as exc:
        return exc.body, exc.status_code
    except Exception as exc:  # noqa: BLE001 - report, do not crash the CLI
        typer.echo(f"fetch failed for {url}: {exc}", err=True)
        return None, None


def _verdict_json(url: str, verdict: Verdict) -> str:
    return json.dumps(
        {"url": url, **asdict(verdict)}, indent=2, sort_keys=True, default=str
    )


def _judge_url(url: str, client: Anthropic | None) -> Verdict:
    source_html, http_status = _fetch_source(url)
    extraction = extract_article(source_html, url) if source_html else None
    extracted_html = extraction.content_html if extraction is not None else None
    chunks = (
        [(chunk.html, chunk.word_count) for chunk in chunk_html(extracted_html)]
        if extracted_html
        else None
    )
    return judge_extraction(
        url=url,
        http_status=http_status,
        source_html=source_html,
        extracted_html=extracted_html,
        chunks=chunks,
        title=extraction.title if extraction is not None else None,
        client=client,
    )


def _rejudge_stored(
    session: Session, article: Article, client: Anthropic | None
) -> None:
    source_html, http_status = _fetch_source(article.url)
    chunks = [(chunk.html, chunk.word_count) for chunk in article.chunks]
    verdict = judge_extraction(
        url=article.url,
        http_status=http_status,
        source_html=source_html,
        extracted_html=article.content_html,
        chunks=chunks or None,
        title=article.title,
        client=client,
    )
    apply_verdict(article, verdict)
    session.commit()
    typer.echo(_verdict_json(article.url, verdict))


@app.command()
def main(
    url: Annotated[
        str | None, typer.Option(help="Fetch, extract and judge one URL.")
    ] = None,
    article: Annotated[
        int | None, typer.Option(help="Re-judge one stored article by id.")
    ] = None,
    judge_all: Annotated[
        bool, typer.Option("--all", help="Re-judge every stored article.")
    ] = False,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Escalate ambiguous cases to Claude."),
    ] = False,
) -> None:
    """Print an extraction-fidelity verdict, and backfill stored articles."""
    load_dotenv(override=False)
    client = fidelity_client() if llm else None
    if url is not None:
        typer.echo(_verdict_json(url, _judge_url(url, client)))
        return
    if article is None and not judge_all:
        typer.echo("pass one of --url, --article or --all", err=True)
        raise typer.Exit(code=2)
    with SessionLocal() as session:
        if article is not None:
            stored = session.get(Article, article)
            if stored is None:
                typer.echo(f"no article with id {article}", err=True)
                raise typer.Exit(code=1)
            targets = [stored]
        else:
            targets = list(session.scalars(select(Article).order_by(Article.id)).all())
        for target in targets:
            _rejudge_stored(session, target, client)
    typer.echo(f"judged {len(targets)} article(s)", err=True)


if __name__ == "__main__":
    app()
