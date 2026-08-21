FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Official Playwright image: Ubuntu + Python 3.12 + Chromium and its system
# libraries, version-matched to the `playwright` Python package in
# pyproject.toml. Keep the two versions in lockstep when upgrading.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=web /web/dist ./web/dist
ENV WEB_DIST=/app/web/dist
ENV PORT=8080
# Chromium is already installed in the base image; this only verifies the
# browser the Python package expects is present (and is a no-op otherwise).
RUN playwright install chromium
CMD ["sh", "-c", "alembic upgrade head && uvicorn nanonerd.reader.main:app --host 0.0.0.0 --port ${PORT}"]
