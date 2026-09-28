# -*- coding: utf-8 -*-
"""
Redis 教学脚本：先跑一遍，看懂 Redis 的 5 个基本操作
运行前确保 redis-server 已启动（PONG 通）
运行: python scripts/redis_demo.py
"""
import redis

# 1. 连接 Redis（默认 localhost:6379）
r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# 先验证连通
print("1) ping ->", r.ping(), "（True=连接成功）")

# 2. SET/GET：字符串（string），最基础
r.set("price:REDMI K80", '{"当前价": "1999", "市场价": "2299"}')
val = r.get("price:REDMI K80")
print("2) SET/GET ->", val)

# 3. EXPIRE：设置过期时间（秒）——价格缓存的"保鲜期"
r.expire("price:REDMI K80", 3600)   # 1 小时后自动消失
ttl = r.ttl("price:REDMI K80")
print("3) 过期时间 TTL =", ttl, "秒（1小时后自动删除，这就是缓存保鲜）")

# 4. HSET/HGETALL：哈希（hash）——用 field 存多个商品的价，一个 key 管一组
r.hset("product:price", "REDMI K80", '{"当前价": "1999", "市场价": "2299"}')
r.hset("product:price", "REDMI K80 Pro", '{"当前价": "3399", "市场价": "3899"}')
r.hset("product:price", "小米14 Pro", '{"当前价": "5099", "市场价": "5599"}')
all_products = r.hgetall("product:price")
print("4) HGETALL -> 共", len(all_products), "个商品：")
for name, price in all_products.items():
    print(f"    {name}: {price}")

# 5. DELETE：删除
r.delete("product:price")
print("5) DEL 后还剩:", r.exists("product:price"), "个（0=已删除）")

print("\n✅ 全跑通了！你现在见过 Redis 最核心的 5 个命令了。")
