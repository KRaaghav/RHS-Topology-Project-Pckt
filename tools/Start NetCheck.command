#!/bin/bash
# double click this file to start NetCheck
cd "$(dirname "$0")"

# already running from before? then just show the page again
if curl -s -o /dev/null http://127.0.0.1:8765; then
    open http://127.0.0.1:8765
    exit 0
fi

python3 netcheck_ui.py
