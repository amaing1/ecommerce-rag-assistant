# 第1行：用哪个基础镜像（Python 3.9，和你的开发环境一致）
FROM python:3.9-slim

# 第2行：设置工作目录（容器里的"项目根目录"）
WORKDIR /app

# 第3行：先复制 requirements.txt（单独复制，利用 Docker 缓存加速）
COPY requirements.txt .

# 第4行：安装依赖（清华源加速；--no-cache-dir 不缓存，减小镜像体积）
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 第5行：复制全部代码进容器
COPY . .

# 第6行：暴露端口（8000 = FastAPI）
EXPOSE 8000

# 第7行：容器启动时运行的命令（启动 FastAPI）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

