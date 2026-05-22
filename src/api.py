from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ai.providers.base import ProviderError
from src.config import SettingsError
from src.core.researcher import Researcher, create_researcher
from src.services.external_policy import is_quota_exhausted
from src.validation import MAX_QUESTION_CHARS, ValidationError, validate_source_names

logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)
    sources: list[str] | None = None
    no_cache: bool = False


class CitationOut(BaseModel):
    index: int
    title: str
    url: str
    origin: str


class FetchResultOut(BaseModel):
    source_type: str
    count: int
    from_cache: bool
    elapsed_seconds: float
    error: str | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[CitationOut]
    degraded: bool
    fetch_results: list[FetchResultOut]


@asynccontextmanager
async def lifespan(app: FastAPI):
    researcher = await create_researcher()
    app.state.researcher = researcher
    try:
        yield
    finally:
        await researcher.close()


app = FastAPI(title="Async Research Assistant", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest) -> AskResponse:
    researcher: Researcher = app.state.researcher
    try:
        source_names = validate_source_names(payload.sources)
        result = await researcher.ask(
            payload.question,
            source_names=source_names,
            no_cache=payload.no_cache,
        )
    except (ValidationError, ValueError, SettingsError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        status_code = 429 if is_quota_exhausted(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("API request failed")
        raise HTTPException(status_code=500, detail="Research failed") from exc

    citations = [
        CitationOut(
            index=citation.index,
            title=citation.source.title,
            url=citation.source.url,
            origin=citation.source.origin,
        )
        for citation in result.answer.citations
    ]
    fetch_results = [
        FetchResultOut(
            source_type=fetch_result.source_type,
            count=len(fetch_result.sources),
            from_cache=fetch_result.from_cache,
            elapsed_seconds=fetch_result.elapsed_seconds,
            error=fetch_result.error,
        )
        for fetch_result in result.fetch_results
    ]
    return AskResponse(
        question=result.answer.question,
        answer=result.answer.answer,
        citations=citations,
        degraded=result.degraded,
        fetch_results=fetch_results,
    )
