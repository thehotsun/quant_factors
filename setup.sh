#!/bin/bash
cd "$(dirname "$0")"

echo "=== quant_factors 环境初始化 ==="

if [ ! -d "quantenv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv quantenv
fi

echo "激活虚拟环境..."
source quantenv/bin/activate

echo "安装依赖..."
pip install -r requirements.txt

mkdir -p logs
mkdir -p data

echo "下载历史数据..."
python download_history.py

echo ""
echo "=== 初始化完成 ==="
echo "启动服务: bash start.sh"
echo "或手动: source quantenv/bin/activate && python server.py"