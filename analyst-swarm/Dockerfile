FROM python:3.12-slim

WORKDIR /app

# Install Node.js (required for Claude CLI) and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY swarm.py .
COPY config.yaml .

# Agent definitions are mounted from the host
# Config override via config.local.yaml mount or env vars
# For claude_cli provider: mount ~/.claude for auth tokens

ENV PYTHONUNBUFFERED=1

CMD ["python", "swarm.py"]
