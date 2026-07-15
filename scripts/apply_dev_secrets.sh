#!/usr/bin/env bash
# Apply the cani-secrets Secret to the dev AKS cluster from an env file that lives
# OUTSIDE the repo (and outside any cloud-synced folder). Manifests are streamed to
# kubectl over stdin — no secret material is ever written inside the repo tree.
#
# Setup + rotation procedure: runbooks/rotate-dev-secrets.md
#
# Note: hub-system receives the same key set as docs-platform even though hub-api never
# touches Qdrant/blob storage — cani_shared.config.Settings declares QDRANT_* and
# AZURE_STORAGE_CONNECTION_STRING as required fields, so every service needs them present
# to boot. Splitting Settings per service (so each namespace gets only what it uses) is a
# tracked follow-up, not something to improvise here.
set -euo pipefail

SECRETS_ENV_FILE="${CANI_DEV_SECRETS_FILE:-$HOME/.cani/dev-secrets.env}"

if [[ ! -f "$SECRETS_ENV_FILE" ]]; then
  echo "error: $SECRETS_ENV_FILE not found." >&2
  echo "Create it per runbooks/rotate-dev-secrets.md (never inside the repo)." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$SECRETS_ENV_FILE"
set +a

REQUIRED_KEYS=(
  CANI_TOKEN_SIGNING_SECRET
  CANI_SESSION_SECRET
  POSTGRES_PASSWORD
  POSTGRES_HOST
  QDRANT_URL
  QDRANT_COLLECTION
  AZURE_STORAGE_CONNECTION_STRING
)

for key in "${REQUIRED_KEYS[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "error: $key is missing or empty in $SECRETS_ENV_FILE" >&2
    exit 1
  fi
done

# Mirror the app's own fail-fast rule (cani_shared.config): a short signing secret must
# never reach the cluster.
if [[ ${#CANI_TOKEN_SIGNING_SECRET} -lt 32 ]]; then
  echo "error: CANI_TOKEN_SIGNING_SECRET must be at least 32 characters" >&2
  exit 1
fi
if [[ ${#CANI_SESSION_SECRET} -lt 32 ]]; then
  echo "error: CANI_SESSION_SECRET must be at least 32 characters" >&2
  exit 1
fi

apply_secret() {
  local namespace="$1"
  kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: cani-secrets
  namespace: ${namespace}
type: Opaque
stringData:
  CANI_TOKEN_SIGNING_SECRET: "${CANI_TOKEN_SIGNING_SECRET}"
  CANI_SESSION_SECRET: "${CANI_SESSION_SECRET}"
  POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
  POSTGRES_HOST: "${POSTGRES_HOST}"
  QDRANT_URL: "${QDRANT_URL}"
  QDRANT_COLLECTION: "${QDRANT_COLLECTION}"
  AZURE_STORAGE_CONNECTION_STRING: "${AZURE_STORAGE_CONNECTION_STRING}"
EOF
}

apply_secret docs-platform
apply_secret hub-system

echo "cani-secrets applied to docs-platform and hub-system."
echo "Restart workloads to pick up new values:"
echo "  kubectl -n hub-system rollout restart deployment/hub-api"
echo "  kubectl -n docs-platform rollout restart deployment/docs-api deployment/retrieval-worker deployment/ingestion-worker"
