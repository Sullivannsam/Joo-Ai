#!/bin/bash

clear

echo "Starting Joo..."

# start ollama only if not running
if ! pgrep -x "ollama" > /dev/null
then
    ollama serve > /dev/null 2>&1 &
fi

sleep 1

python3 main.py
