FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 -m pastedrop && mkdir -p /data/uploads && chown -R pastedrop:pastedrop /data
COPY app ./app
USER pastedrop
EXPOSE 8766
CMD ["python", "-m", "app"]
