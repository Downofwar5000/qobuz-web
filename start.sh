#!/bin/bash

# If no qobuz-dl config exists yet, prompt the user to create one
if [ ! -f /root/.config/qobuz-dl/config.ini ]; then
    echo "-------------------------------------------------------"
    echo " No qobuz-dl config found. Run this once to set it up:"
    echo "   docker exec -it qobuz-web qobuz-dl -r"
    echo "-------------------------------------------------------"
fi

python /app/app.py
