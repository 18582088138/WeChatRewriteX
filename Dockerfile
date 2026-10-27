# 文枢 - 自媒体 Studio 运行时镜像（可选容器化方案，用于服务器环境批量部署）
# 构建：docker build -t wenshu-studio:1.6.0 .
# 运行：docker run -d -p 8000:8000 -v wenshu-resource:/app/resource -v wenshu-log:/app/log \
#         --name wenshu wenshu-studio:1.6.0
# 密钥：把 .env 放到挂载的 /app/resource 同级？否——.env 在 /app/.env，可用 --env-file 注入：
#       docker run -d --env-file .env -p 8000:8000 ... 
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

EXPOSE 8000
VOLUME ["/app/resource", "/app/log"]

# 容器内以仓库形态运行（config/ 就地存在 → RUNTIME_ROOT=/app）
CMD ["python", "-m", "app", "--host", "0.0.0.0", "--no-browser"]
