"""
售后单查询工具（Agent 工具调用）
售后单 = 退货/换货/维修工单，模拟数据，只读查询
"""

import re
from typing import Optional, Dict

# ===== 模拟售后单库：key=售后单号，value=售后信息 =====
_AFTER_SALES: Dict[str, dict] = {
    "SH20260815001": {
        "after_sales_no": "SH20260815001",
        "order_no": "XM20260815001",        # 关联的订单号
        "product": "小米14 Pro 手机（16GB+512GB）",
        "type": "退货退款",
        "status": "退款中",
        "amount": 4999.00,
        "progress": [
            "2026-08-16 10:20 已提交退货申请",
            "2026-08-16 15:30 审核通过，请寄回商品",
            "2026-08-18 09:00 仓库已签收，退款处理中",
        ],
        "eta": "预计 3 个工作日内原路退回",
    },
    "SH20260805002": {
        "after_sales_no": "SH20260805002",
        "order_no": "XM20260800002",
        "product": "小米手环9 NFC版（曜石黑）",
        "type": "换货",
        "status": "已完成",
        "amount": 279.00,
        "progress": [
            "2026-08-05 11:00 已提交换货申请",
            "2026-08-06 09:20 审核通过",
            "2026-08-08 16:40 新商品已发出",
            "2026-08-10 12:10 换货完成，已签收",
        ],
        "eta": "已完成",
    },
    "SH20260810003": {
        "after_sales_no": "SH20260810003",
        "order_no": "XM20260800003",
        "product": "小米智能门锁 E30（深空灰）",
        "type": "维修",
        "status": "待审核",
        "amount": 0.00,
        "progress": ["2026-08-17 14:05 已提交维修申请，等待审核"],
        "eta": "预计 24 小时内审核",
    },
}
# 售后单号格式：SH + 10 位数字
_AFTER_SALES_NO_PATTERN = re.compile(r"(SH\d{10,})", re.IGNORECASE)


def extract_after_sales_no(question: str) -> Optional[str]:
    """从用户问题里提取售后单号"""
    m = _AFTER_SALES_NO_PATTERN.search(question)
    return m.group(1).upper() if m else None


def query_after_sales(question: str) -> Optional[dict]:
    """查询售后单：返回售后单字典；查不到返回 None"""
    no = extract_after_sales_no(question)
    if no and no in _AFTER_SALES:
        return _AFTER_SALES[no]
    return None


def format_after_sales_snapshot(after_sales: dict) -> str:
    """把售后单信息格式化成给大模型的文本"""
    lines = [
        f"售后单号: {after_sales['after_sales_no']}",
        f"关联订单: {after_sales['order_no']}",
        f"商品: {after_sales['product']}",
        f"类型: {after_sales['type']}",
        f"状态: {after_sales['status']}",
        f"金额: ¥{after_sales['amount']:.2f}",
        f"预计: {after_sales['eta']}",
        "处理进度:",
    ]
    for step in after_sales.get("progress", []):
        lines.append(f"  - {step}")
    return "\n".join(lines)