FROM python:3.12-slim

COPY . /gateway

WORKDIR /gateway

RUN pip install --no-cache-dir -r requirements.txt

CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
