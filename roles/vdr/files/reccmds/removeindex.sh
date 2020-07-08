#!/bin/dash
find "$1" -maxdepth 1 \( -name "index" -o -name "index.vdr" \) -delete
