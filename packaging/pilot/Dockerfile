# Stage 1 only. Build from tools/pilot/build_context.py output, NEVER the repo root.
# Multi-architecture base digest and Debian snapshot verified 2026-09-10.
FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DTM_CLOUD=0 \
    LANG=C.UTF-8 LC_ALL=C.UTF-8
COPY debian.sources /etc/apt/sources.list.d/debian.sources
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress fontconfig fonts-crosextra-carlito fonts-crosextra-caladea \
    fonts-liberation2 fonts-dejavu-core fonts-dejavu-extra fonts-linuxlibertine \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f
WORKDIR /opt/builder
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
COPY relay.py /opt/pilot-relay.py
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --uid 10001 --create-home pilot \
    && mkdir -p /pilot-data/workspace \
    && chown -R pilot:pilot /pilot-data
USER 10001:10001
EXPOSE 7665
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7665/healthz', timeout=2).read()"
ENTRYPOINT ["python", "-m", "dtm_buildsheet.headless"]
CMD ["--host", "0.0.0.0", "--port", "7665", "--workspace", "/pilot-data/workspace", "--seed-fixtures"]
