#!/usr/bin/sh
find "$1" -maxdepth 1 -type f \( -name "resume" -o name "resume.*" \) -delete
