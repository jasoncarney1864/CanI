#!/usr/bin/env bash
set -euo pipefail

# Create migration script
cat > /tmp/migration.py << 'EOF'
import os
import psycopg
conn = psycopg.connect(os.environ["POSTGRES_DSN"])
conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
conn.commit()
print("Migration 0003 applied: display_name column added")
EOF

echo "Applying migration to AKS cluster..."

# Run via az aks command invoke
az aks command invoke \
  -g cani-workload-core-canido-dev-eastus2-rgca86c588 \
  -n cani-aks33874b17 \
  --file /tmp/migration.py \
  --command "kubectl -n hub-system exec -i hub-api-5d9967cf6-7v4qd -- python" \
  -o json | jq -r '.logs'

echo "Migration complete"
