FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd -m figurauser
RUN mkdir -p /app/data/avatars && chown -R figurauser:figurauser /app/data
COPY --chown=figurauser:figurauser . .
USER figurauser
CMD ["python", "server.py"]
