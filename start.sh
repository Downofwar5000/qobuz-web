#!/bin/bash

# Make qobuz-dl find its config inside the /config volume Unraid provides
mkdir -p /config/qobuz-dl
mkdir -p /root/.config

# Symlink so qobuz-dl's expected path points to the persisted volume
ln -sfn /config/qobuz-dl /root/.config/qobuz-dl

echo "[start] Config path: $(ls /root/.config/qobuz-dl/ 2>/dev/null || echo 'EMPTY — run: docker exec -it qobuz-web qobuz-dl -r')"
echo "[start] Download dir: $DOWNLOAD_DIR"

python /app/app.py
