FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir numpy
COPY audio_message.py codebook.py emitter.py reply_engine.py simple_qr.py ./
COPY docs ./docs
RUN mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
ENV ALIVE_STATE_FILE=/data/state.json
ENV HOME=/data
EXPOSE 8765
CMD ["python", "-u", "emitter.py", "--http", "--wifi-device", "--serve-only", "--host", "0.0.0.0", "--port", "8765"]
