# ocr_pipeline — image เดียวใช้ทั้ง local และ production (design doc §7)
# build:  docker build -f ocr_pipeline/Dockerfile -t fraud-risk-pipeline-v2 .
# run:    docker run --rm -v $(pwd):/app fraud-risk-pipeline-v2 \
#             python -m ocr_pipeline.run --from-ocr ... (หรือ --pdf ... เมื่อมี TYPHOON_OCR_API_KEY)
FROM python:3.11-slim

# poppler สำหรับงาน PDF (pin ผ่าน base image กัน drift)
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ocr_pipeline/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# โค้ด + reference data (version ตาม git)
COPY ocr_pipeline/ /app/ocr_pipeline/

CMD ["python", "-m", "ocr_pipeline.run", "--help"]
