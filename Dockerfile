FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME=/tmp
ENV TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    fonts-dejavu \
    fonts-liberation \
    libxinerama1 \
    libxrender1 \
    libxext6 \
    libgl1 \
    pdftk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY plantilla.pdf /app/plantilla.pdf

EXPOSE 8000
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000"]
