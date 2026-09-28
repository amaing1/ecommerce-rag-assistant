"""
批量导入脚本 - 自动扫描文件夹上传所有支持的文档格式
使用方法：python scripts/batch_upload.py
"""

import os
import requests
from dotenv import load_dotenv

# 关键:脚本在 scripts/ 目录,.env 在项目根目录(上一级)
# __file__ 是脚本自己的路径,dirname 两次 = 从 scripts 上到项目根
# __file__	当前脚本文件自己的路径	...\scripts\batch_upload.py
# os.path.abspath(x)	把路径变绝对路径	scripts\batch_upload.py → C:\...\scripts\batch_upload.py
# os.path.dirname(x)	取路径的"上一层目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR,".env"))
# ================================================================
# 配置区
# ================================================================
UPLOAD_URL = "http://localhost:8000/knowledge/upload"  # 后端上传接口地址
LOGIN_URL = "http://localhost:8000/auth/login"            # 登录接口
USERNAME = os.getenv("BATCH_USERNAME")
PASSWORD = os.getenv("BATCH_PASSWORD")


# ================================================================
# 函数0：登录拿 token
# ================================================================
def login():
    resp = requests.post(
        LOGIN_URL,
        json={"username":USERNAME,"password":PASSWORD},
        timeout=300
    )
    if resp.status_code !=200:
        print(f"❌ 登录失败({resp.status_code}): {resp.text}")
        print("   请检查 scripts/batch_upload.py 里的 USERNAME / PASSWORD")
        exit(1)
    token = resp.json()["access_token"]
    print("✅ 登录成功,已获取 token")
    return token

# ================================================================
# 函数1：扫描文件夹，找出所有支持的格式文件
# ================================================================
def get_file_list(folder):
    """
    遍历文件夹（包含子文件夹），返回所有符合格式的文件路径列表

    参数：folder - 要扫描的文件夹路径
    返回：list - 文件完整路径列表
    """
    # 支持的文件格式（与后端 knowledge.py 白名单保持一致）
    allowed_extensions = (
        '.pdf', '.txt', '.md', '.docx', '.xlsx', '.xls',
        '.html', '.htm', '.pptx', '.ppt', '.json', '.csv'
    )

    file_paths = []  # 存储所有找到的文件路径

    # os.walk 递归遍历文件夹：(当前目录, 子文件夹列表, 文件列表)
    for root, dirs, files in os.walk(folder):
        for file in files:
            # 如果文件后缀在白名单里，拼完整路径加入列表
            if file.endswith(allowed_extensions):
                file_paths.append(os.path.join(root, file))

    return file_paths


# ================================================================
# 函数2：上传单个文件（带本地去重）
# ================================================================
def upload_file(file_path, seen):
    """
    上传一个文件，如果已经上传过则跳过

    参数：
        file_path - 要上传的文件完整路径
        seen - 已上传文件的去重键集合（set）
    返回：
        True - 上传成功
        False - 跳过（已存在）或上传失败
    """
    # ---- 第1步：计算去重键 ----
    file_name = os.path.basename(file_path)      # 从完整路径中提取文件名
    file_size = os.path.getsize(file_path)       # 获取文件大小（字节数）
    key = f"{file_name}_{file_size}"             # 去重键 = 文件名 + 文件大小

    # ---- 第2步：检查是否已上传过 ----
    if key in seen:
        print(f"⏭️ 跳过（已存在）: {file_name}")
        return False  # 已存在，不上传

    # ---- 第3步：调用后端接口上传 ----
    try:
        # 以二进制模式打开文件（PDF等必须是二进制模式）
        with open(file_path, 'rb') as f:
            # 构造 requests 要求的文件格式：{'字段名': (文件名, 文件对象)}
            files = {'file': (file_name, f)}

            # 发送 POST 请求,带上 token(上传接口需要鉴权)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = requests.post(UPLOAD_URL, files=files, headers=headers)

        # ---- 第4步：处理响应 ----
        if response.status_code == 200:
            # 上传成功 → 记录去重键，下次再遇到就跳过
            seen.add(key)
            print(f"✅ 上传成功: {file_name}")
            return True
        else:
            # 状态码不是 200 → 打印错误信息（比如后端去重拦截返回400）
            print(f"❌ 上传失败 ({response.status_code}): {file_name}")
            # 如果后端返回了错误详情，也打印出来
            try:
                error_detail = response.json().get('detail', '')
                if error_detail:
                    print(f"   原因: {error_detail}")
            except:
                pass
            return False

    except Exception as e:
        # 网络不通、超时等异常
        print(f"❌ 上传异常: {file_name} - {e}")
        return False


# ================================================================
# 函数3：主程序
# ================================================================
def main():
    """
    主流程：
        1. 让用户输入文件夹路径
        2. 扫描文件夹得到所有文件列表
        3. 依次上传每个文件（重复的自动跳过）
        4. 打印完成统计
    """
    global TOKEN
    print("=" * 50)
    print("📂 批量导入知识库脚本")
    print("=" * 50)

    # ---- 第0步：登录拿 token ----
    TOKEN = login()

    # ---- 第1步：获取文件夹路径 ----
    folder = input("请输入要扫描的文件夹路径: ").strip()

    # 检查路径是否存在
    if not os.path.exists(folder):
        print("❌ 文件夹不存在，请检查路径")
        return

    # ---- 第2步：扫描文件 ----
    files = get_file_list(folder)
    print(f"📂 找到 {len(files)} 个文件")

    # 如果没有文件，提前退出
    if len(files) == 0:
        print("⚠️ 没有找到支持格式的文件")
        print(f"   支持的格式: .pdf, .txt, .md, .docx, .xlsx, .xls, .html, .htm, .pptx, .ppt, .json, .csv")
        return

    # ---- 第3步：逐个上传 ----
    seen = set()           # 存放已上传文件的去重键
    success_count = 0      # 成功上传计数
    skip_count = 0         # 跳过计数

    for file_path in files:
        if upload_file(file_path, seen):
            success_count += 1
        else:
            # 如果返回 False，可能是跳过也可能是失败，再判断一次
            # 这里简化处理：统计跳过的需要额外逻辑，暂不细分
            pass

    # ---- 第4步：打印总结 ----
    print("=" * 50)
    print(f"🎉 完成！成功上传 {success_count}/{len(files)} 个文件")
    print("=" * 50)


# ================================================================
# 程序入口
# ================================================================
if __name__ == "__main__":
    main()