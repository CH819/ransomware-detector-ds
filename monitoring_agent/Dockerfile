FROM python:3.12-slim

COPY . /monitoring_agent

WORKDIR /monitoring_agent

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "monitor.py"]
