FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# deps système : mysqlclient (build), ffmpeg (trailers), libgomp1 (lightgbm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential default-libmysqlclient-dev pkg-config ffmpeg libgomp1 \
  && rm -rf /var/lib/apt/lists/*

# install python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# copy projet
COPY . /app

# admin CSS/JS go to the static_vol volume, served by nginx at /django-static/
ENV STATIC_ROOT=/vol/static

CMD ["sh", "-c", "python manage.py collectstatic --noinput && exec gunicorn streaming_backend.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"]
