# 使用官方 Python 3.10 镜像作为基础
FROM python:3.10-slim

# 设置工作目录（容器内的 /app 目录）
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制整个项目到容器内
COPY . .

# 暴露端口（FastAPI 默认 8000）
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]