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

# Hugging Face Spaces expects port 7860
EXPOSE 7860

# Start Uvicorn on port 7860 for Hugging Face Spaces
CMD ["uvicorn", "knowledge_service_poc_clean:app", "--host", "0.0.0.0", "--port", "7860"]
