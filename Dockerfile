FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 app:application"]
