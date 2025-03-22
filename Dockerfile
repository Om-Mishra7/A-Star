FROM python:3.10-slim

# Install necessary dependencies and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential gcc g++ python3-dev \
  && rm -rf /var/lib/apt/lists/*

# Set environment variables for better performance
ENV PYTHONUNBUFFERED=1 \
  PYTHONOPTIMIZE=1 \
  GUNICORN_CMD_ARGS="--workers 4 --threads 2 --log-level info --access-logfile - --error-logfile -"

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

WORKDIR /app/backend

# Optimized Gunicorn command for better performance without async workers
CMD ["gunicorn", "--bind", "0.0.0.0:5632", "main:app"]
