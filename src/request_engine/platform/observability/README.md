# Observability boundary

OpenTelemetry is a process/deployment concern.

Business modules must not import the OpenTelemetry SDK or exporter packages. API and worker
processes are instrumented at startup with the deployment runtime under
`deploy/observability/`.

This keeps telemetry vendor-neutral and prevents observability failures from becoming
domain dependencies.
