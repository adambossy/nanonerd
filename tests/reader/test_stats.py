from datetime import UTC, datetime, time, timedelta

from nanonerd.reader.models import Article, Category, Chunk, ReadingSession
from tests.reader.webapp import create_test_client


def seed_reading_data(factory):
    now = datetime.now(UTC)
    with factory() as session:
        finished = Article(
            url="https://example.com/done",
            title="Done",
            status="ready",
            word_count=200,
            categories=[Category(name="Transit")],
            chunks=[
                Chunk(position=0, html="<p>a</p>", word_count=120, read_at=now),
                Chunk(position=1, html="<p>b</p>", word_count=80, read_at=now),
            ],
        )
        ignored = Article(
            url="https://example.com/ignored",
            title="Ignored",
            status="ready",
            word_count=300,
            categories=[Category(name="Security")],
            chunks=[Chunk(position=0, html="<p>c</p>", word_count=300)],
        )
        uncategorized = Article(
            url="https://example.com/uncat",
            title="Uncat",
            status="ready",
            word_count=100,
            chunks=[Chunk(position=0, html="<p>d</p>", word_count=100, read_at=now)],
        )
        session.add_all([finished, ignored, uncategorized])
        session.commit()
        session.add_all(
            [
                ReadingSession(
                    article_id=finished.id,
                    started_at=now,
                    last_active_at=now,
                    active_seconds=600,
                ),
                ReadingSession(
                    article_id=finished.id,
                    started_at=now - timedelta(days=1),
                    last_active_at=now - timedelta(days=1),
                    active_seconds=120,
                ),
                ReadingSession(
                    article_id=uncategorized.id,
                    started_at=now,
                    last_active_at=now,
                    active_seconds=60,
                ),
            ]
        )
        session.commit()


def test_stats_totals_and_topic_attribution(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_reading_data(factory)

    output = client.get("/api/stats").json()

    assert output["totals"] == {
        "active_seconds": 780,
        "articles_saved": 3,
        "articles_finished": 2,
        "words_read": 300,
    }
    topics = {t["name"]: t for t in output["topics"]}
    expected_topics = {
        "Transit": {
            "name": "Transit",
            "saved": 1,
            "read_through": 100.0,
            "active_seconds": 720,
        },
        "Security": {
            "name": "Security",
            "saved": 1,
            "read_through": 0.0,
            "active_seconds": 0,
        },
        "(uncategorized)": {
            "name": "(uncategorized)",
            "saved": 1,
            "read_through": 100.0,
            "active_seconds": 60,
        },
    }
    assert topics == expected_topics
    assert output["topics"][0]["name"] == "Transit"


def test_stats_daily_rollup_zero_fills_30_days(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_reading_data(factory)

    daily = client.get("/api/stats").json()["daily"]

    assert len(daily) == 30
    assert daily[-1]["active_seconds"] == 660
    assert daily[-2]["active_seconds"] == 120
    assert daily[0]["active_seconds"] == 0


def test_stats_top_articles_sorted_by_time(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_reading_data(factory)

    top = client.get("/api/stats").json()["top_articles"]

    assert [(t["title"], t["active_seconds"]) for t in top] == [
        ("Done", 720),
        ("Uncat", 60),
    ]


def test_stats_empty_database(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)

    output = client.get("/api/stats").json()

    assert output["totals"] == {
        "active_seconds": 0,
        "articles_saved": 0,
        "articles_finished": 0,
        "words_read": 0,
    }
    assert (output["topics"], output["top_articles"]) == ([], [])
    assert len(output["daily"]) == 30


def test_stats_daily_window_includes_early_morning_session(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)

    # Regression test: ensure sessions at early morning on the oldest window day
    # are included in the daily rollup (window_start must be day-aligned to midnight)
    now = datetime.now(UTC)
    oldest_day = now.date() - timedelta(days=29)
    early_morning_start = datetime.combine(oldest_day, time(minute=30), tzinfo=UTC)

    with factory() as session:
        article = Article(
            url="https://example.com/early",
            title="Early",
            status="ready",
            word_count=50,
            chunks=[Chunk(position=0, html="<p>early</p>", word_count=50)],
        )
        session.add(article)
        session.commit()
        session.add(
            ReadingSession(
                article_id=article.id,
                started_at=early_morning_start,
                last_active_at=early_morning_start,
                active_seconds=300,
            )
        )
        session.commit()

    output = client.get("/api/stats").json()

    # daily[0] is the oldest day; it should include the early morning session
    assert output["daily"][0]["active_seconds"] == 300
