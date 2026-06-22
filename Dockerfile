FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set PYTHONPATH so 'from app.xxx import' works from the /app working directory
ENV PYTHONPATH=/app

RUN chmod +x start.sh

CMD ["bash", "start.sh"]
