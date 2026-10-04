# RepoAtlas production image.
# python:3.13-slim keeps the image small; git is added because RepoAtlas clones
# repositories with the git command-line tool.
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before code: Docker caches each step, so a code-only change
# reuses this (slow) layer instead of reinstalling NumPy and SciPy.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# Don't run as root: the server handles untrusted input (other people's repos).
# /app/data holds the SQLite cache, so the app user must be able to write it.
RUN useradd --create-home --uid 10001 atlas \
 && mkdir -p /app/data \
 && chown atlas:atlas /app/data
USER atlas

ENV PYTHONUNBUFFERED=1 \
    PORT=8000
EXPOSE 8000

# Hosts like Render say which port to listen on through $PORT, so the command
# goes through `sh -c` to expand it. `exec` makes uvicorn the main process, so
# it receives the platform's stop signal and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
