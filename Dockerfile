FROM python:3.10-slim

# 设置工作目录与环境变量
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# 安装基础系统库与中文字体支持
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-microhei \
    default-mysql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 运行依赖
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 拷贝全量工程代码
COPY . /app/

EXPOSE 8000

# 启动脚本：等待 DB 就绪后启动
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
