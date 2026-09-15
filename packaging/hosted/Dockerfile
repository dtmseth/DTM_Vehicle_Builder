# Boundary image only; use tools/pilot/hosted_build_context.py, never the checkout.
FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DTM_CLOUD=0 DTM_RUNTIME_MODE=hosted \
    DTM_WORKSPACE_DIR=/tmp/dtm-hosted-workspace DTM_ARTIFACT_ROOT=/tmp/dtm-artifacts
WORKDIR /opt/builder
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && python -m pip check && useradd --uid 10001 --create-home hosted
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
  CMD python -c "import os,urllib.request,urllib.parse; origin=os.environ['DTM_HOSTED_ORIGIN']; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/healthz',headers={'Host':urllib.parse.urlsplit(origin).netloc}),timeout=2).read()"
ENTRYPOINT ["python", "-m", "dtm_buildsheet.app.hosted.bootstrap"]
CMD ["--host", "0.0.0.0"]
