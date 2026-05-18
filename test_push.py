#!/usr/bin/env python3
"""
量化报告推送测试脚本
使用假数据测试：量化系统 → 工作流引擎 → QQ 频道
"""
import requests
import json
import sys

WORKFLOW_URL = "http://localhost:3000/events/manual"
HEALTH_URL = "http://localhost:3000/health"

def check_workflow_engine():
    """检查工作流引擎是否运行"""
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code == 200:
            print("✅ 工作流引擎运行正常")
            return True
        else:
            print(f"❌ 工作流引擎异常: {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ 工作流引擎未运行: {e}")
        return False

def send_test_report():
    """发送测试报告"""
    fake_report = """📊 量化分析日报 - 测试数据
日期: 2026-05-18

🟢 综合信号: BUY | 强度: 0.65 | 置信度: 0.72
信号数: 3 (BUY:2 SELL:1)

📈 因子明细:
1. 生猪期货: BUY - 猪价 20日涨 8.5%，产能去化预期
2. 豆粕期货: BUY - 大豆进口成本上升，饲料涨价传导
3. 玉米期货: SELL - 供应充裕，库存高位

⚠️ 风险提示:
- 宏观数据滞后，CPI/PMI 待更新
- 动力煤限价，铝链信号仅依赖 Z-score

---
此为测试数据，仅用于验证推送链路"""

    payload = {
        "text": f"【量化日报】测试报告\n\n{fake_report}",
        "channelId": "qqbot:c2c:671E406CE85706E91F0CF251BD7D8177",
    }

    try:
        r = requests.post(WORKFLOW_URL, json=payload, timeout=10)
        print(f"📤 发送测试报告: {r.status_code}")
        print(f"   响应: {r.text[:200]}")
        return r.status_code in (200, 202)
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False

def main():
    print("=" * 50)
    print("量化报告推送测试")
    print("=" * 50)
    print()

    # Step 1: 检查工作流引擎
    if not check_workflow_engine():
        sys.exit(1)

    # Step 2: 发送测试报告
    print()
    if send_test_report():
        print()
        print("✅ 测试完成！请检查 QQ 是否收到消息")
        print("   如果没收到，检查:")
        print("   1. 工作流引擎日志: journalctl --user -u workflow-engine -f")
        print("   2. OpenClaw 日志: journalctl --user -u openclaw-gateway -f")
    else:
        print()
        print("❌ 测试失败")

if __name__ == "__main__":
    main()
