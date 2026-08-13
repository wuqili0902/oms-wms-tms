# oms-wms-tms Helm Chart

Deploy the OMS+WMS+TMS platform to Kubernetes.

## Prerequisites

- Helm 3.x
- A cluster with an Ingress controller (nginx recommended)
- cert-manager if using the bundled TLS issuer

## Dependencies

This chart depends on the Bitnami PostgreSQL and Redis charts.
Fetch them before first install:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency update deploy/helm/tms
```

## Install

```bash
helm upgrade --install oms-wms-tms deploy/helm/tms \
  --namespace logistics --create-namespace \
  --set env.SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  --set postgresql.auth.password='change-me' \
  --set env.CORS_ORIGINS='["https://oms.example.com"]'
```

## Configuration

All tunables live in `values.yaml`. Key sections:

| Section | Purpose |
|---------|---------|
| `env` | Application environment variables (SecretKey + ConfigMap) |
| `postgresql` | Bitnami PostgreSQL subchart overrides |
| `redis` | Bitnami Redis subchart overrides |
| `celery` | Worker replicas/concurrency, beat toggle |
| `autoscaling` | HPA for the app deployment |
| `backup` | Scheduled pg_dump CronJob + PVC |

## Notes

- Migrations run as a Helm hook Job (`alembic upgrade head`) on install/upgrade.
- The app image also runs migrations on boot (idempotent); with many replicas
  a migration Job is preferred and the boot migration keeps single-pod
  rollouts safe.
- Backups require `PG_PASSWORD`; it is rendered from
  `postgresql.auth.password` into the release Secret.