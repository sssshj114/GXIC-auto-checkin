# ============================================================
# 学会学课堂 - 自动签到系统 Dockerfile
# ============================================================
FROM docker.m.daocloud.io/library/python:3.10-slim

LABEL maintainer="Pixe1"
LABEL description="学会学课堂 - 自动签到与全栈代答系统"

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用模块
COPY src/ ./src/
COPY app.py .

# 数据目录
RUN mkdir -p /data
VOLUME ["/data"]

# 非 root 运行
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /data
USER appuser

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')"

# 默认环境变量
ENV HEADLESS=1
ENV DATA_DIR=/data
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "auto_checkin"]
