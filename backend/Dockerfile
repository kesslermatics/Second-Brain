FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --timeout=120 --retries=5 --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE ${PORT}

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
