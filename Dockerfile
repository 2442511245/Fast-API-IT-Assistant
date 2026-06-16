# 使用官方 Python 3.10 镜像作为基础
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装（不使用任何镜像源，直连官方 PyPI）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 单独安装 PyTorch CPU 版本（Railway 无 GPU，CPU 版体积小、下载快）
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 复制整个项目到容器内
COPY . .

# 启动命令：使用 $PORT 环境变量（Railway 自动注入），绑定 0.0.0.0
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]