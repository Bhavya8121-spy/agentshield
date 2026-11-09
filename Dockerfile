FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENTSHIELD_HOST=0.0.0.0 PORT=8765
COPY requirements-demo.txt ./
COPY requirements-live.txt ./
ARG INSTALL_LIVE=0
RUN pip install --no-cache-dir -r requirements-demo.txt \
 && if [ "$INSTALL_LIVE" = "1" ]; then pip install --no-cache-dir -r requirements-live.txt; fi
COPY security/ ./security/
COPY tools/ ./tools/
COPY agents/ ./agents/
COPY product_server.py paste_check.py ./
COPY web/ ./web/
# Files copied from a Mac can be owner-only; make them readable by the non-root user.
RUN chmod -R a+rX /app
USER 65532:65532
EXPOSE 8765
CMD ["python", "product_server.py"]