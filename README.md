# RepoAtlas

Paste a public GitHub repo URL → get an interactive map of how its Python modules depend on each other, with graph analytics (importance, clusters, circular dependencies).

> 🚧 Work in progress — full README with screenshots, architecture and design decisions coming soon.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest -q                        # run the tests
```

Requires Python 3.11+ and `git` on your PATH. `requirements.txt` holds only what the server needs at runtime; `requirements-dev.txt` adds the test tools.
