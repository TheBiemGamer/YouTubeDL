FROM python:3.9-slim
LABEL org.opencontainers.image.source https://github.com/thebiemgamer/youtubedl

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir gunicorn

COPY . /app

EXPOSE 5000

CMD ["gunicorn", "--worker-class", "gevent", "-w", "4", "-b", "0.0.0.0:5000", "youtubedl.app:app"]