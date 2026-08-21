FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
# Headless Chromium for faithful-snapshot capture (playwright pins the build
# matching the installed python package; --with-deps pulls the apt libs).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=web /web/dist ./web/dist
ENV WEB_DIST=/app/web/dist
ENV PORT=8080
CMD ["sh", "-c", "alembic upgrade head && uvicorn nanonerd.reader.main:app --host 0.0.0.0 --port ${PORT}"]
