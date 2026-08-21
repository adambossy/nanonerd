"""Re-run extraction for stored articles.

python -m nanonerd.reader.reprocess --all
python -m nanonerd.reader.reprocess 12 15 23
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
import typer

from nanonerd.reader.db import SessionLocal
from nanonerd.reader.models import Article
from nanonerd.reader.pipeline import process_article

app = typer.Typer(add_completion=False)


@dataclass(frozen=True, slots=True)
class ReprocessResult:
    article_id: int
    status: str
    error: str | None


def _all_article_ids(factory: sessionmaker[Session]) -> list[int]:
    with factory() as session:
        return list(session.scalars(select(Article.id).order_by(Article.id)).all())


def _mark_pending(factory: sessionmaker[Session], article_id: int) -> bool:
    with factory() as session:
        article = session.get(Article, article_id)
        if article is None:
            return False
        article.status = "pending"
        article.error = None
        session.commit()
        return True


def _result_of(factory: sessionmaker[Session], article_id: int) -> ReprocessResult:
    with factory() as session:
        article = session.get(Article, article_id)
        if article is None:
            return ReprocessResult(article_id, "missing", None)
        return ReprocessResult(article_id, article.status, article.error)


def reprocess_articles(
    article_ids: list[int],
    *,
    session_factory: sessionmaker[Session] | None = None,
    report: Callable[[ReprocessResult], None] | None = None,
) -> list[ReprocessResult]:
    """Reset each article to pending and run the extraction pipeline again."""
    factory = session_factory if session_factory is not None else SessionLocal
    results: list[ReprocessResult] = []
    for article_id in article_ids:
        if _mark_pending(factory, article_id):
            process_article(article_id, session_factory=factory)
        result = _result_of(factory, article_id)
        results.append(result)
        if report is not None:
            report(result)
    return results


def _print_result(result: ReprocessResult) -> None:
    detail = f" ({result.error})" if result.error else ""
    typer.echo(f"{result.article_id}: {result.status}{detail}")


@app.command()
def main(
    ids: Annotated[
        list[int] | None, typer.Argument(help="Article ids to reprocess.")
    ] = None,
    reprocess_all: Annotated[
        bool, typer.Option("--all", help="Reprocess every stored article.")
    ] = False,
) -> None:
    """Re-extract and re-chunk articles with the current pipeline."""
    load_dotenv(override=False)
    if reprocess_all:
        article_ids = _all_article_ids(SessionLocal)
    elif ids:
        article_ids = list(ids)
    else:
        raise typer.BadParameter("pass article ids or --all")
    results = reprocess_articles(article_ids, report=_print_result)
    ready = sum(1 for result in results if result.status == "ready")
    typer.echo(f"done: {ready}/{len(results)} ready")


if __name__ == "__main__":
    app()
