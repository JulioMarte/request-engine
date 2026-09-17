FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /e2e

RUN useradd --create-home --uid 10002 e2e
COPY tests/system_e2e/runner.py /e2e/runner.py
RUN mkdir -p /artifacts && chown -R e2e:e2e /e2e /artifacts

USER e2e
ENTRYPOINT ["python", "/e2e/runner.py"]
CMD ["run", "smoke"]
