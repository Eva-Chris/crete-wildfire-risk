FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Copy data files into /app/data/
RUN mkdir -p /app/data
COPY *.geojson /app/data/
COPY *.npz /app/data/
COPY *.pkl /app/data/
COPY *.tif /app/data/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]