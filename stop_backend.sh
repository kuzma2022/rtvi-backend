#!/bin/bash
PID=$(ps aux | grep 'bot_runner.py' | grep -v grep | awk '{print $2}')

if [ -n "$PID" ]; then
  kill $PID
  echo "进程已终止！"
else
  echo "未找到运行中的进程。"
fi
