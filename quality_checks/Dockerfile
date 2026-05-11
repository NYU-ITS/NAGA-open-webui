FROM prom/prometheus:v3.2.1 AS prometheus

FROM mcr.microsoft.com/playwright:v1.59.1-noble

WORKDIR /workspace

COPY --from=prometheus /bin/prometheus /usr/local/bin/prometheus

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

RUN chmod +x ./scripts/run_openshift_frontend_quality_checks.sh ./scripts/run_openshift_frontend_quality_checks_from_build.sh ./scripts/write_grafana_cloud_prometheus_config.py ./scripts/upload_openshift_playwright_artifacts.py \
    && chgrp -R 0 /workspace \
    && chmod -R g=u /workspace

ENV HOME=/tmp \
    CI=1 \
    PLAYWRIGHT_VIDEO=on \
    PLAYWRIGHT_RUN_LIVE=1 \
    PLAYWRIGHT_SKIP_WEB_SERVER=1 \
    PLAYWRIGHT_TIMEOUT=60000

CMD ["bash", "scripts/run_openshift_frontend_quality_checks.sh"]
