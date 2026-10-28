FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WENSHU_DATA_DIR=/app/resource \
    WENSHU_LOG_DIR=/app/log
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python -m playwright install --with-deps chromium \
    && useradd --uid 10001 --create-home wenshu \
    && mkdir -p /app/resource /app/log \
    && chown -R wenshu:wenshu /app/resource /app/log
COPY app/ ./app/
COPY config/ ./config/
COPY --from=web /web/dist ./web/dist
USER wenshu
EXPOSE 8000
VOLUME ["/app/resource", "/app/log"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
# Supply APP_ACCESS_TOKEN using --env-file or -e; remote binding requires it.
CMD ["python", "-m", "app", "--host", "0.0.0.0", "--no-browser"]
