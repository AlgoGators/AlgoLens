FROM python:3.9-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend files only
COPY backend/ /app/backend/

# Set working directory to backend
WORKDIR /app/backend

# Command to run the application
CMD ["python", "app.py"]