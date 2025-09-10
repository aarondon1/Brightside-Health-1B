FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Install the package
RUN pip install -e .

# Create data directories
RUN mkdir -p data/raw data/processed data/ontologies outputs

# Expose Streamlit port
EXPOSE 8501

# Run Streamlit by default
CMD ["streamlit", "run", "src/visualization/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
