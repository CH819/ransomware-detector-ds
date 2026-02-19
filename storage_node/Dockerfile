FROM python:3.12-slim

COPY . /storage_node

WORKDIR /storage_node

RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /storage_node

CMD ["python", "snapshot_handler.py"]
