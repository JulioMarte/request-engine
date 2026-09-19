FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /e2e

RUN useradd --create-home --uid 10002 e2e
COPY deploy/reference/e2e-runner-requirements.txt /e2e/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /e2e/requirements.txt
COPY tests/system_e2e/runner.py /e2e/runner.py
COPY tests/system_e2e/event_sink.py /e2e/event_sink.py
COPY tests/fixtures/software_webauthn_authenticator.py /e2e/software_webauthn_authenticator.py
RUN mkdir -p /artifacts /sink && chown -R e2e:e2e /e2e /artifacts /sink

USER e2e
ENTRYPOINT ["python", "/e2e/runner.py"]
CMD ["run", "smoke"]
