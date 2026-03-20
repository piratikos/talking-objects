FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p uploads results
EXPOSE 10000
CMD ["python", "web_app.py", "--port", "10000", "--no-browser"]
