FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
# Source files may arrive owner-only (NAS ACLs); the server runs as nobody.
RUN chmod -R a+rX /srv
USER nobody
EXPOSE 8000
CMD ["python", "server.py"]
