"""
订单/物流查询工具（Agent 工具调用）
演示项目用内存模拟订单库充当"外部订单系统"
"""

import re   ##正则表达式，抠出订单号
from typing import Optional, Dict
# ===== 模拟订单库：key=订单号，value=订单信息 =====
_ORDERS: Dict[str, dict] = {
    "XM20260815001": {
        "order_no": "XM20260815001",
        "product": "小米14 Pro 手机（16GB+512GB）",
        "status": "运输中",
        "courier": "顺丰速运",
        "tracking_no": "SF1357902468642",
        "tracking": [
            "2026-08-15 14:20 商家已发货",
            "2026-08-16 09:32 快件已发出，正在发往【上海】",
        ],
        "eta": "预计 2026-08-18 前送达",
    },
    "XM20260800002": {
        "order_no": "XM20260800002",
        "product": "小米手环9 NFC版（曜石黑）",
        "status": "已签收",
        "courier": "中通快递",
        "tracking_no": "ZT8866442200113",
        "tracking": [
            "2026-08-02 10:05 商家已发货",
            "2026-08-04 15:40 快件已签收，签收人：本人",
        ],
        "eta": "已送达",
    },
    "XM20260800003": {
        "order_no": "XM20260800003",
        "product": "小米智能门锁 E30（深空灰）",
        "status": "待发货",
        "courier": "未分配",
        "tracking_no": "",
        "tracking": ["2026-07-20 09:12 订单已支付，等待商家发货"],
        "eta": "预计 48 小时内发货",
    },
}
#订单号格式：XM + 10位数字
_ORDERS_NO_PATTERN = re.compile(r"(XM\d{10,})", re.IGNORECASE)  #re.IGNORECASE  忽略大小写
##订单/物流意图识别关键词
_INTENT_KEYWORDS = ["订单","物流","快递","发货","签收","到哪","到货"]


def is_order_intent(question: str) -> bool:
    """判断用户是否在问订单/物流"""
    q = question.lower()  #问题转小写
    if _ORDERS_NO_PATTERN.search(q):
        return True
    for i in _INTENT_KEYWORDS:
        if i in q:
            return True
    return False


def query_order(question: str):
    """从问题里抠出订单号，去订单库里去查，返回订单信息"""
    m = _ORDERS_NO_PATTERN.search(question)  #从用户话里面找订单号
    if m and m.group(1).upper() in _ORDERS:  #找到了，且库里真有这个号
        return _ORDERS[m.group(1).upper()]   # 把订单号当钥匙，取出那个订单的字典
    return None


