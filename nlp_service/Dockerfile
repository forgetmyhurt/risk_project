FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir flask jieba requests -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY . /app
EXPOSE 8001
CMD ["python", "app.py"]
