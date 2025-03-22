FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
  build-essential gcc g++ python3-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

WORKDIR /app/backend

# Set Gunicorn logging to output to stdout
CMD ["gunicorn", "--bind", "0.0.0.0:5632", "main:app", "--log-level", "debug", "--access-logfile", "-", "--error-logfile", "-"]
