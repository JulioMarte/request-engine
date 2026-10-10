FROM public.ecr.aws/docker/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /provider
COPY deploy/reference/smtp-provider-requirements.txt /provider/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /provider/requirements.txt \
    && useradd --create-home --uid 10003 smtp-provider
COPY tests/system_e2e/smtp_provider_lab.py /provider/smtp_provider_lab.py
USER smtp-provider
EXPOSE 1025 8091
ENTRYPOINT ["python", "/provider/smtp_provider_lab.py"]
