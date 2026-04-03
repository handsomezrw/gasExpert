FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-rag.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-rag.txt

COPY app/ app/
COPY data/ data/

ENV LOG_FORMAT=json
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
