# Use official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install Tesseract OCR and OpenCV system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install gunicorn
RUN pip install -r requirements.txt

# Copy the Django project
COPY . /app/

# Run database migrations
RUN python manage.py migrate

# Expose the port Render uses
EXPOSE 10000

# Start Gunicorn server
CMD ["gunicorn", "nexmed.wsgi:application", "--bind", "0.0.0.0:10000"]