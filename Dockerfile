# InferForge app image — shared by the web (gunicorn) and worker (celery)
# containers. The ONNX model is NEVER baked in: bind-mount ./models at
# runtime (see docker-compose.yml).
FROM python:3.12-slim

# opencv runtime libs (imdecode/imencode, drawing) + onnxruntime's libgomp
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Layer-cache pip: requirements change rarely, code changes often
COPY requirements.txt requirements-async.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-async.txt

COPY . .

# Model-existence check + mkdir logs + exec gunicorn (start.sh)
CMD ["bash", "./start.sh"]
