# Metis Learning Engine — Railway-compatible Python image.
# Scaffold-only build; the real M7 image will pin ML deps separately.
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir 'fastapi>=0.115.0' 'uvicorn[standard]>=0.32.0'

COPY app ./app

ENV PORT=9001
EXPOSE 9001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9001"]
