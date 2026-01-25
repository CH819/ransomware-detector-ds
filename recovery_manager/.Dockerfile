FROM python:3.12-slim

COPY . /recovery_manager

RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /recovery_manager

CMD ["python", "recovery_manager.py"]
