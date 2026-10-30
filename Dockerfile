# ── Stage 1: Node / Vite build ──────────────────────────────────────────────
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend-build

WORKDIR /build/web
# Trust corporate SSL-inspection CAs for npm (populated by deploy.sh; no-op if
# empty) and drop distrusted roots. --use-openssl-ca makes Node read only the
# filtered file: its compiled-in roots can't be edited and may include them.
COPY docker/ca-bundle.pem docker/distrust_cas_node.js docker/distrusted_cas.json /tmp/
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV NODE_OPTIONS=--use-openssl-ca
RUN node /tmp/distrust_cas_node.js && rm /tmp/distrust_cas_node.js /tmp/distrusted_cas.json /tmp/ca-bundle.pem
COPY web/package.json web/package-lock.json ./
RUN npm ci --prefer-offline

COPY web/ ./
# Vite config already sets outDir = "../api/static"
RUN npm run build


# ── Stage 2: Python runtime ──────────────────────────────────────────────────
# Pinned to the multi-arch index digest. Dependabot opens the digest bumps, which
# is how base image security fixes arrive. Python minor version upgrades are
# intentional, not automatic.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS runtime

WORKDIR /app

# System deps:
# - git: needed by pip for plugin installs from GitHub URLs (pip install git+https://...)
# xmlsec, lxml and sqlcipher3 install from wheels that bundle their native
# libraries, so no -dev packages are needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Inject host trust store (populated by scripts/build.sh; no-op if empty).
# Captures corporate SSL-inspection CAs so zscaler-sdk-python calls succeed.
COPY docker/ca-bundle.pem /usr/local/share/ca-certificates/zs-config-bundle.crt
# The host store can reintroduce distrusted roots, so filter after it is copied.
# Rebuilds the trust store and fails the build if a distrusted root survives.
COPY docker/distrust_cas.py docker/distrusted_cas.json /tmp/
RUN python /tmp/distrust_cas.py && rm /tmp/distrust_cas.py /tmp/distrusted_cas.json

# Install Python deps from the hashed lockfile, wheels only, so a package without
# a wheel fails here rather than compiling. pip stays in the image for plugin
# installs, so the base image's copy has to be current too.
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --upgrade "pip==26.2.2" \
    && pip install --no-cache-dir --only-binary :all: --require-hashes -r requirements.lock \
    && pip install --no-cache-dir --no-deps .

# Copy application source
COPY api/          ./api/
COPY cli/          ./cli/
COPY db/           ./db/
COPY lib/          ./lib/
COPY services/     ./services/
COPY entrypoint.sh ./entrypoint.sh
RUN sed -i 's/\r//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Copy compiled frontend from stage 1
COPY --from=frontend-build /build/api/static ./api/static

# Data directories — real content comes from mounted volumes
RUN mkdir -p /data/db /data/plugins

# Non-root user for defence-in-depth
RUN useradd -r -u 1001 -g root zsconfig && chown -R zsconfig:root /app /data
USER zsconfig

ENV ZS_CONTAINER_MODE=1
ENV ZSCALER_DB_PATH=/data/db/zscaler.db
ENV ZS_PLUGIN_DIR=/data/plugins
ENV PYTHONUSERBASE=/data/plugins
ENV PYTHONUNBUFFERED=1
# The pip install above runs before the source is copied, so it installs the
# zs-config console script but no packages; resolve them from /app instead.
ENV PYTHONPATH=/app
# Point HOME at the persistent DB volume so the Fernet key file
# (~/.config/zs-config/secret.key) survives container restarts and image upgrades.
ENV HOME=/data/db
# Point requests and Python's ssl module at the system trust store so
# zscaler-sdk-python honours corporate SSL-inspection CAs injected at build time.
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["/app/entrypoint.sh"]
