FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/

# ENTRYPOINT/CMD split lets `docker compose run agent agent.smoke` swap the module.
ENTRYPOINT ["python", "-m"]
CMD ["agent.cli"]
