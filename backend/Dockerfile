# Bookworm is pinned because Playwright's --with-deps install fails on the newer
# Debian that the plain slim tag points to.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv

# Installs dependencies before copying the code, so code changes rebuild quickly.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

# Chromium comes from the installed Playwright, so their versions always match.
RUN if python -c "import playwright" 2>/dev/null; then \
        playwright install --with-deps chromium; \
    fi

COPY app ./app

RUN useradd --create-home haq && chown -R haq /srv
USER haq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4)"

# One process only: runs, SSE subscribers and profiles all live in its memory.
# Only Caddy can reach this port, so its forwarded client IP can be trusted.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
