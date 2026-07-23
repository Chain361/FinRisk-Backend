FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY seed_database.py .
COPY standardized_data/ standardized_data/
COPY src/ src/

RUN python3 seed_database.py --force

ENV FRAUD_RISK_DB=/app/fraud_risk.db
EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
