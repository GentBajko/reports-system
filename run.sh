uv run gunicorn src.backend.server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
