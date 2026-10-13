FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    DATABASE_PATH=/data/site.db \
    UPLOAD_DIRECTORY=/data/uploads

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup --system web \
    && adduser --system --ingroup web web \
    && mkdir -p /data \
    && chown web:web /data

COPY app ./app
RUN chown -R web:web /app

USER web
EXPOSE 8000
STOPSIGNAL SIGINT

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]