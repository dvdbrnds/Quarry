## Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
# Skip tsc in-container (types checked in CI/local) to cut peak RAM; Vite alone still needs headroom.
ENV NODE_OPTIONS="--max-old-space-size=1536"
RUN npm run build:docker

## Stage 2: Python backend + nginx
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev nginx supervisor curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -r -s /bin/false appuser && \
    mkdir -p /app/uploads /var/log/nginx /var/lib/nginx /run && \
    chown -R appuser:appuser /app /var/log/nginx /var/lib/nginx /run

COPY backend/ .
COPY --from=frontend-build /app/dist /var/www/html

COPY nginx.conf /etc/nginx/sites-available/default
COPY supervisord.conf /etc/supervisor/conf.d/quarry.conf

RUN mkdir -p /app/uploads && \
    sed -i 's|/run/nginx.pid|/run/nginx.pid|' /etc/nginx/nginx.conf && \
    sed -i 's|pid /var/run/nginx.pid|pid /run/nginx.pid|' /etc/nginx/nginx.conf && \
    chown -R appuser:appuser /app /var/www/html /var/log/nginx /var/lib/nginx /run /etc/nginx && \
    chmod 755 /var/log/nginx /var/lib/nginx /run

EXPOSE 3200

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

USER appuser

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/quarry.conf"]
