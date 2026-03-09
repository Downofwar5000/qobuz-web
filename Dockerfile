FROM python:3.11-slim

# trickle = per-process bandwidth limiter
RUN apt-get update && apt-get install -y trickle \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask qobuz-dl

WORKDIR /app
COPY app/ .

# Persistent dirs for downloads and qobuz-dl credentials
RUN mkdir -p /downloads /root/.config/qobuz-dl

EXPOSE 5000
COPY start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
