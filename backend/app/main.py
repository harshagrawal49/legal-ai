from contextlib import asynccontextmanager

import openai

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import cases, judgments
from app.db import init_db
from app.llm.client import LLMRefusal


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Nyaya Research API", lifespan=lifespan)
app.include_router(cases.router)
app.include_router(judgments.router)


@app.exception_handler(LLMRefusal)
def refusal_handler(request: Request, exc: LLMRefusal):
    return JSONResponse(status_code=422, content={"detail": "The assistant could not process this request."})


@app.exception_handler(openai.APIStatusError)
@app.exception_handler(openai.APIConnectionError)
def llm_unavailable_handler(request: Request, exc: openai.APIError):
    # The client already retried; the provider is overloaded, rate-limiting, or unreachable.
    status = getattr(exc, "status_code", None)
    if status is not None and status < 500 and status != 429:
        raise exc
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "30"},
        content={"detail": "The AI service is busy right now. Please try again in a minute."},
    )


@app.get("/health")
def health():
    return {"ok": True}
