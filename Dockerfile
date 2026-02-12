# Use a lightweight Python base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed (e.g., for building some python packages)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY main.py .
COPY src/ src/
COPY static/ static/

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "main.py", "serve", "--host", "0.0.0.0"]
