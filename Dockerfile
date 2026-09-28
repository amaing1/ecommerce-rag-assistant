# 第1行：用哪个基础镜像（Python 3.9，和你的开发环境一致）
FROM python:3.9-slim

# 第2行：设置工作目录（容器里的"项目根目录"）
WORKDIR /app

# 第3行：先复制 requirements.txt（单独复制，利用 Docker 缓存加速）
COPY requirements.txt .

# 第4行：安装依赖（清华源加速；--no-cache-dir 不缓存，减小镜像体积）
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 换 Debian 国内源（playwright --with-deps 要用 apt 装系统依赖，官方源国内极慢，先换成阿里云）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    true

# 价格爬虫用 Playwright 无头浏览器，需额外下载 Chromium 浏览器程序（--with-deps 顺便装系统依赖）
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
RUN playwright install --with-deps chromium

# 第5行：复制全部代码进容器
COPY . .

# 第6行：暴露端口（8000 = FastAPI）
EXPOSE 8000

# 第7行：容器启动时运行的命令（启动 FastAPI）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

