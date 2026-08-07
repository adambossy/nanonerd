from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader import pipeline
from nanonerd.reader.api import router
from nanonerd.reader.db import get_session
from nanonerd.reader.models import Base
from nanonerd.reader.stats import router as stats_router


def create_test_client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(router)
    app.include_router(stats_router)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override

    processed = []
    monkeypatch.setattr(
        pipeline, "process_article", lambda article_id: processed.append(article_id)
    )
    return TestClient(app), factory, processed
