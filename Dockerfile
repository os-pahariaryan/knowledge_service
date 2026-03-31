FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# IMPORTANT: Install Playwright browsers (required by crawl4ai)
# This prevents crashes when hitting /ingest/url
RUN playwright install --with-deps chromium

# Copy the actual application files
COPY . .

# Standard FastAPI port
EXPOSE 8000

# Start Uvicorn, listening on all interfaces. Render automatically maps the PORT.
CMD ["sh", "-c", "uvicorn knowledge_service_poc_clean:app --host 0.0.0.0 --port ${PORT:-8000}"]
