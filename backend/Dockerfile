# syntax=docker/dockerfile:1.7
# Backend API image (CPU-only PyTorch for the cross-encoder reranker).

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface

# ---- dependencies (cached layer) -------------------------------------------------------
FROM base AS deps
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime ---------------------------------------------------------------------------
FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY --chown=app:app app ./app
COPY --chown=app:app evaluations ./evaluations
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app pyproject.toml ./

# Optionally bake the reranker weights into the image so containers never download at
# runtime:  docker build --build-arg PRELOAD_RERANKER=true .
ARG PRELOAD_RERANKER=false
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RUN mkdir -p /app/data /app/.cache/huggingface && chown -R app:app /app/data /app/.cache
USER app
RUN if [ "$PRELOAD_RERANKER" = "true" ]; then \
      python -c "from sentence_transformers import CrossEncoder; CrossEncoder('$RERANKER_MODEL')"; \
    fi

EXPOSE 8000
# Secrets are provided at runtime via environment variables – never baked into the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

# PORT is honoured for platforms such as Render. One worker keeps the in-memory BM25
# index and in-process job state consistent (see README "Scaling").
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 20"]
