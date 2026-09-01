#!/bin/bash
# Двоен клик = стартувај ја апликацијата „Оптимизација"
cd "$(dirname "$0")"

# Стопирај стар процес ако постои
OLD=$(lsof -ti:5002 2>/dev/null)
[ -n "$OLD" ] && kill -9 $OLD 2>/dev/null && sleep 1

# Најди python (venv од стариот проект ако постои, инаку системски)
if [ -f "../Battery_optimization/.venv/bin/python" ]; then
    PY="../Battery_optimization/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PY="python3"
else
    PY="python"
fi

# Отвори browser по 4 секунди, стартувај сервер
(sleep 4 && open "http://127.0.0.1:5002/") &
$PY api.py
