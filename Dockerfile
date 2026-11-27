FROM python:3.15.2-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    HOME=/tmp/islandos-home \
    XDG_CACHE_HOME=/tmp/xdg-cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501

WORKDIR /app
COPY requirements-runtime.lock ./requirements-runtime.lock
RUN python -m pip install --no-cache-dir --upgrade "pip==26.2.2" && \
    python -m pip install --no-cache-dir -r requirements-runtime.lock && \
    python -m pip check
COPY . .
# Run without root privileges. Runtime caches and transient files are redirected
# to /tmp so Compose and CI can enforce a read-only root filesystem.
RUN useradd --create-home --uid 10001 islandos && chown -R islandos:islandos /app
USER islandos

EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()" || exit 1
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
