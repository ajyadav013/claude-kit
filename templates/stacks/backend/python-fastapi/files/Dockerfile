FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Install the application (and its dependencies) from source.
COPY . .
RUN pip install .

EXPOSE 8000

# The compose file runs migrations before starting the server; this is the default for a bare run.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
