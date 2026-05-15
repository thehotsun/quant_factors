#!/bin/bash
cd "$(dirname "$0")"
source quantenv/bin/activate
nohup python server.py > logs/server.log 2>&1 &
echo "Flask 服务已启动，PID: $!"
