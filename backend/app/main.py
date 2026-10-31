import logging
import threading
from contextlib import asynccontextmanager

import openai

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import cases, documents, judgments
from app.db import SessionLocal, init_db
from app.llm.client import LLMRefusal
from app.services import documents as documents_service
from app.services import ocr
from app.services.embeddings import embed_query

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        documents_service.recover_interrupted(db)
    threading.Thread(target=ocr.log_status, daemon=True).start()  # checks which OCR engine is installed
    # Load the embedding model now rather than on the first search (saves several seconds there).
    threading.Thread(target=lambda: embed_query("warm up"), daemon=True).start()
    yield


app = FastAPI(title="Nyaya Research API", lifespan=lifespan)
app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(documents.library)
app.include_router(judgments.router)


@app.exception_handler(LLMRefusal)
def refusal_handler(request: Request, exc: LLMRefusal):
    return JSONResponse(status_code=422, content={"detail": "The assistant can't help with this request. Describe your situation and the lawful outcome you want, or contact NALSA legal aid (15100)."})


@app.exception_handler(openai.APIStatusError)
@app.exception_handler(openai.APIConnectionError)
def llm_unavailable_handler(request: Request, exc: openai.APIError):
    # The client already retried; the provider is overloaded, rate-limiting, or unreachable.
    status = getattr(exc, "status_code", None)
    log.warning("LLM call failed on %s %s: %s %s", request.method, request.url.path, status, exc)
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
