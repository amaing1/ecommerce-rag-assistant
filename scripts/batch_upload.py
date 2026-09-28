"""
批量导入脚本 - 自动扫描文件夹上传所有支持的文档格式
使用方法：python scripts/batch_upload.py
"""

import os
import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR,".env"))

UPLOAD_URL = "http://localhost:8000/knowledge/upload"
LOGIN_URL = "http://localhost:8000/auth/login"
USERNAME = os.getenv("BATCH_USERNAME")
PASSWORD = os.getenv("BATCH_PASSWORD")


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

    file_paths = []

    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.endswith(allowed_extensions):
                file_paths.append(os.path.join(root, file))

    return file_paths


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
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    key = f"{file_name}_{file_size}"

    if key in seen:
        print(f"⏭️ 跳过（已存在）: {file_name}")
        return False

    try:
        with open(file_path, 'rb') as f:
            # requests 的 files 格式：{'字段名': (文件名, 文件对象)}
            files = {'file': (file_name, f)}
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = requests.post(UPLOAD_URL, files=files, headers=headers)

        if response.status_code == 200:
            seen.add(key)
            print(f"✅ 上传成功: {file_name}")
            return True
        else:
            print(f"❌ 上传失败 ({response.status_code}): {file_name}")
            try:
                error_detail = response.json().get('detail', '')
                if error_detail:
                    print(f"   原因: {error_detail}")
            except:
                pass
            return False

    except Exception as e:
        print(f"❌ 上传异常: {file_name} - {e}")
        return False


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

    TOKEN = login()

    folder = input("请输入要扫描的文件夹路径: ").strip()

    if not os.path.exists(folder):
        print("❌ 文件夹不存在，请检查路径")
        return

    files = get_file_list(folder)
    print(f"📂 找到 {len(files)} 个文件")

    if len(files) == 0:
        print("⚠️ 没有找到支持格式的文件")
        print(f"   支持的格式: .pdf, .txt, .md, .docx, .xlsx, .xls, .html, .htm, .pptx, .ppt, .json, .csv")
        return

    seen = set()
    success_count = 0
    skip_count = 0

    for file_path in files:
        if upload_file(file_path, seen):
            success_count += 1
        else:
            pass

    print("=" * 50)
    print(f"🎉 完成！成功上传 {success_count}/{len(files)} 个文件")
    print("=" * 50)


if __name__ == "__main__":
    main()