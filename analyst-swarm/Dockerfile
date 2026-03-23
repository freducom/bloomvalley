FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY swarm.py .
COPY config.yaml .

# Agent definitions are mounted from the host
# Config override via config.local.yaml mount or env vars

ENV PYTHONUNBUFFERED=1

CMD ["python", "swarm.py"]
