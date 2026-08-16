# Small, production-oriented image. python:3.11-slim keeps the image size
# down versus the full python:3.11 image, without needing Alpine's musl
# libc (which occasionally causes weird issues with compiled Python deps).
FROM python:3.11-slim

WORKDIR /app

# Copy requirements first and install before copying the rest of the app.
# Docker caches layers -- as long as requirements.txt doesn't change,
# rebuilding after an app code change won't reinstall dependencies from
# scratch, which makes iteration much faster.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# No --reload here (that's a dev-only flag). In Phase 9 (load testing) we
# may add --workers for multi-process concurrency within a single
# container; for now, one process per container, and horizontal scale
# comes from running multiple containers (rl1, rl2, rl3) -- see
# docker-compose.yml.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]