# Stage 1: Build stage
FROM python:3.13-slim AS builder

# Set work directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Copy only requirements to cache them in docker layer
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Stage 2: Runtime stage
FROM python:3.13-slim

# Set work directory
WORKDIR /app

# Install runtime dependencies (adjust as needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev libssl-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy necessary files from builder
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app .

# Create necessary directories
RUN mkdir -p /app/logs /app/database

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "main.py"]

