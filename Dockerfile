
FROM node:24-bookworm-slim AS web
WORKDIR /build
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install --no-audit --no-fund; fi
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd -g 10001 dashboard && useradd -u 10001 -g 10001 -m dashboard \
    && mkdir -p /app/data /codex && chown -R 10001:10001 /app/data /codex
COPY pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir .
RUN apt-get update && apt-get install -y --no-install-recommends texlive-latex-extra texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

FROM base AS app
COPY --from=web /build/dist ./frontend/dist
USER 10001:10001
EXPOSE 8000
CMD ["python","-m","uvicorn","backend.main:create_app","--factory","--host","0.0.0.0","--port","8000","--no-access-log"]

FROM node:24-bookworm-slim AS codex
RUN npm install -g @openai/codex@0.169.0

FROM base AS worker
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && pip install --no-cache-dir '.[boards]'
USER 10001:10001
CMD ["python","-m","backend.discovery"]
