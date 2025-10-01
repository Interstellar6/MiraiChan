#!/bin/bash

# 设置日志目录
LOG_DIR="./logs"
mkdir -p $LOG_DIR

# 获取时间戳
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "正在启动机器人服务..."

# 检查 Lagrange 目录是否存在
if [ ! -d "Lagrange" ]; then
    echo "错误: Lagrange 目录不存在!"
    exit 1
fi

# 检查 Lagrange.OneBot 可执行文件
if [ ! -f "Lagrange/Lagrange.OneBot" ]; then
    echo "错误: Lagrange/Lagrange.OneBot 可执行文件不存在!"
    exit 1
fi

# 启动 Lagrange.OneBot
echo "启动 Lagrange.OneBot..."
(
    cd Lagrange
    if [ $? -ne 0 ]; then
        echo "错误: 无法进入 Lagrange 目录!"
        exit 1
    fi

    nohup ./Lagrange.OneBot > ../$LOG_DIR/lagrange_$TIMESTAMP.log 2>&1 &
    LAGRANGE_PID=$!
    echo $LAGRANGE_PID > ../$LOG_DIR/lagrange.pid
    echo "✓ Lagrange.OneBot 已启动 (PID: $LAGRANGE_PID)"
)

# 等待服务初始化
echo "等待服务初始化..."
for i in {1..10}; do
    echo -n "."
    sleep 1
done
echo ""

# 启动 melobot
echo "启动 melobot..."
nohup uv run python -m melobot run src/bot.py > $LOG_DIR/bot_$TIMESTAMP.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > $LOG_DIR/bot.pid
echo "✓ melobot 已启动 (PID: $BOT_PID)"

# 保存所有 PID
echo "服务启动完成！"
echo "进程信息:"
echo "  - Lagrange.OneBot: PID $(cat $LOG_DIR/lagrange.pid)"
echo "  - melobot: PID $BOT_PID"
echo "日志文件: $LOG_DIR/"
echo "使用 'tail -f $LOG_DIR/bot_$TIMESTAMP.log' 查看实时日志"

# 等待进程结束
wait