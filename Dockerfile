FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY reflex ./reflex
COPY packages ./packages
COPY data ./data
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
COPY apps/eval ./apps/eval
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install -e .

EXPOSE 8000
# Render/Railway inject PORT; plain Docker (and Antideploy) leaves it unset
# and the app should keep listening on 8000.
CMD ["sh", "-c", "exec uvicorn reflex.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
