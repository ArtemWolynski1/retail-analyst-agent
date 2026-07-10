FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/
COPY prompts/ prompts/
COPY data/ data/
COPY tests/ tests/
COPY pytest.ini .

# ENTRYPOINT/CMD split lets the module be swapped per run:
#   docker compose run agent agent.smoke     — setup validator
#   docker compose run agent pytest -m live  — live prompt-policy suite
ENTRYPOINT ["python", "-m"]
CMD ["agent.cli"]
