"""OpenAI-compatible FastAPI adapter for the optional local OpenVINO model."""

from __future__ import annotations

import asyncio
import importlib
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.http_observability import HttpObservabilityMiddleware, RequestBodyLimitMiddleware
from src.logging_config import configure_logging
from src.metrics import metrics_response

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = Path(
    os.getenv(
        "HORRAGOR_LLM_MODEL_PATH",
        str(PROJECT_ROOT / "models" / "Qwen3-8B-int4-cw-ov"),
    )
)
MODEL_ID = os.getenv("HORRAGOR_LLM_MODEL", "qwen3-8b-npu")
DEVICE = os.getenv("HORRAGOR_LLM_DEVICE", "AUTO")

logger = configure_logging("model-api")


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    model: str = Field(default=MODEL_ID, min_length=1, max_length=256)
    messages: list[Message] = Field(min_length=1, max_length=50)
    max_tokens: int = Field(default=512, ge=1, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


def _token_count(tokenizer: Any, text: str) -> int:
    """Count tokens with the same tokenizer used by the OpenVINO pipeline."""
    return int(tokenizer.encode(text).input_ids.get_size())


def _clean_answer(answer: str) -> str:
    """Remove Qwen's optional reasoning wrapper from the public response."""
    cleaned = answer.strip()
    if cleaned.startswith("<think>") and "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1].lstrip()
    return cleaned


def _load_pipeline() -> tuple[Any, Any]:
    if not MODEL_PATH.is_dir():
        raise RuntimeError(f"OpenVINO model directory not found: {MODEL_PATH}")
    try:
        openvino_genai = importlib.import_module("openvino_genai")
    except ImportError as exc:
        raise RuntimeError("Install the model extra to run the OpenVINO service") from exc
    pipeline = openvino_genai.LLMPipeline(str(MODEL_PATH), device=DEVICE)
    return pipeline, pipeline.get_tokenizer()


@asynccontextmanager
async def lifespan(application: FastAPI):
    pipeline, tokenizer = await run_in_threadpool(_load_pipeline)
    application.state.pipeline = pipeline
    application.state.tokenizer = tokenizer
    application.state.generation_lock = asyncio.Lock()
    logger.info("OpenVINO model ready", model=MODEL_ID, device=DEVICE)
    yield
    application.state.pipeline = None
    application.state.tokenizer = None
    logger.info("OpenVINO model API stopped")


app = FastAPI(title="HorRAGor Local Model API", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=262_144)
app.add_middleware(HttpObservabilityMiddleware, service="model-api")


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest) -> dict[str, Any]:
    pipeline = getattr(app.state, "pipeline", None)
    tokenizer = getattr(app.state, "tokenizer", None)
    generation_lock = getattr(app.state, "generation_lock", None)
    if pipeline is None or tokenizer is None or generation_lock is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The local model is not ready.",
        )

    messages = [message.model_dump() for message in request.messages]
    prompt = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        extra_context={"enable_thinking": False},
    )
    generation_options: dict[str, Any] = {
        "max_new_tokens": request.max_tokens,
        "do_sample": request.temperature > 0,
    }
    if request.temperature > 0:
        generation_options["temperature"] = request.temperature

    async with generation_lock:
        raw_answer = await run_in_threadpool(
            pipeline.generate,
            prompt,
            **generation_options,
        )
    answer = _clean_answer(str(raw_answer))
    prompt_tokens, completion_tokens = await asyncio.gather(
        run_in_threadpool(_token_count, tokenizer, prompt),
        run_in_threadpool(_token_count, tokenizer, answer),
    )

    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.get("/v1/models")
async def models() -> dict[str, list[dict[str, str]]]:
    return {"data": [{"id": MODEL_ID}]}


@app.get("/health")
async def health() -> dict[str, str]:
    if getattr(app.state, "pipeline", None) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The local model is not ready.",
        )
    return {
        "status": "healthy",
        "model": MODEL_ID,
        "model_path": str(MODEL_PATH),
        "device": DEVICE,
    }


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    return metrics_response()
