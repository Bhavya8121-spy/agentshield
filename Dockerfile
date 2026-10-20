FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENTSHIELD_HOST=0.0.0.0 PORT=8765
COPY requirements-demo.txt ./
RUN pip install --no-cache-dir -r requirements-demo.txt
COPY security/ ./security/
COPY tools/ ./tools/
COPY product_server.py paste_check.py ./
COPY web/ ./web/
USER 65532:65532
EXPOSE 8765
CMD ["python", "product_server.py"]
