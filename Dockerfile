# FlowlyStack: one image for linux/amd64 and linux/arm64 (Mac Intel and Apple Silicon, Linux, Windows, Raspberry Pi on a 64-bit OS).
FROM python:3.12-slim

# One dependency list, like run.sh: pyproject.toml. Copied first so a code change does not reinstall everything.
RUN pip install --no-cache-dir uv==0.5.14
WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY backend ./backend
COPY frontend ./frontend
COPY hooks ./hooks
COPY CHANGELOG.md ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/merge_hooks.py ./docker/merge_hooks.py

# HOME is where the app looks for ~/.claude and ~/.codex: the compose file mounts only the folders the Dashboard reads, read-only, under it.
# FLOWLYSTACK_LIVE_BY_ACTIVITY: a container cannot see the host's processes, so "running now" means "transcript changed in the last 2 minutes".
ENV HOME=/home/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLOWLYSTACK_PROMPTS_DIR=/app/prompts \
    FLOWLYSTACK_IN_DOCKER=1 \
    FLOWLYSTACK_LIVE_BY_ACTIVITY=1
RUN mkdir -p /app/data /app/prompts /home/app && chmod 755 /home/app && chown 1000:1000 /app/data /app/prompts

# Image labels (late in the file so changing them never reinstalls the dependencies). The release workflow sets the same
# description (scripts/check_image_labels.py keeps the copies equal) and fills source, url, version and revision from the repository.
LABEL org.opencontainers.image.title="FlowlyStack" \
      org.opencontainers.image.description="A private workspace on your own computer to keep, connect and plan your AI prompts." \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/cent822/flowlystack" \
      org.opencontainers.image.url="https://github.com/cent822/flowlystack"

EXPOSE 8372
VOLUME ["/app/data", "/app/prompts"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8372/api/auth/state', timeout=4)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8372", "--timeout-graceful-shutdown", "1"]
