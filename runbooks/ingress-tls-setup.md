# Public ingress + TLS setup (Sprint 3 C1)

How CanI is reachable on the public internet at `https://<ingress-ip>.sslip.io` with a
valid Let's Encrypt certificate. Most of it is IaC (Pulumi + kustomize); the two one-time
pieces below are done by hand because they are cluster-wide installs / IP-derived.

## Architecture

- **Managed NGINX ingress** — the AKS web-app-routing addon (enabled in
  `infra/modules/compute_aks.py`, `ingress_profile.web_app_routing`). It runs an
  Azure-managed NGINX controller + a public LoadBalancer in `app-routing-system`. Ingress
  class: `webapprouting.kubernetes.azure.com`.
- **cert-manager** — issues the Let's Encrypt cert via HTTP-01, solved through that nginx
  class. ClusterIssuers are IaC (`k8s/base/ingress/cluster-issuers.yaml`).
- **Web Ingress** (`k8s/base/web/ingress.yaml`) — host `<ip>.sslip.io`, TLS from
  cert-manager, backend the web Service. Only the web app is exposed; the APIs stay
  private and are reached via the web app's server-side proxy.
- **NetworkPolicies** (`k8s/base/network-policies.yaml`) — `web-from-ingress` (controller
  -> web pod) and `acme-http01-solver` (controller -> the ACME solver pod, which deny-all
  would otherwise block).

## One-time step 1: install cert-manager

cert-manager is a cluster-wide third-party install, not part of our kustomize. Install a
pinned release once (repeat to upgrade):

```bash
SCRATCH=$(mktemp -d)
VER=$(curl -s https://api.github.com/repos/cert-manager/cert-manager/releases/latest \
  | python -c "import sys,json;print(json.load(sys.stdin)['tag_name'])")
curl -sL "https://github.com/cert-manager/cert-manager/releases/download/$VER/cert-manager.yaml" \
  -o "$SCRATCH/cert-manager.yaml"
az aks command invoke -g <workload-rg> -n <cluster> \
  --command 'kubectl apply -f cert-manager.yaml
             kubectl -n cert-manager rollout status deploy/cert-manager --timeout=180s
             kubectl -n cert-manager rollout status deploy/cert-manager-webhook --timeout=180s
             kubectl -n cert-manager rollout status deploy/cert-manager-cainjector --timeout=120s' \
  --file "$SCRATCH/cert-manager.yaml"
```

## One-time step 2: the sslip.io host tracks the ingress IP

The web Ingress host is `<managed-nginx-lb-ip>.sslip.io`. Get the current IP:

```bash
az aks command invoke -g <workload-rg> -n <cluster> --command \
  'kubectl -n app-routing-system get svc nginx -o jsonpath="{.status.loadBalancer.ingress[0].ip}"'
```

If it differs from the host in `k8s/base/web/ingress.yaml`, update the host there (both the
`tls.hosts` entry and the `rules.host`), delete the `web-tls` secret in docs-platform, and
let CD re-apply — cert-manager re-issues for the new host. In dev the LoadBalancer IP is
stable, so this is rare.

## Verify

```bash
curl -sS -o /dev/null -w "%{http_code} ssl_verify=%{ssl_verify_result}\n" \
  https://<ip>.sslip.io/api/health          # 200 ssl_verify=0 (valid cert)
curl -sS http://<ip>.sslip.io/api/health -o /dev/null -w "%{http_code}\n"   # 308 -> https
```

## Notes

- Issuance uses `letsencrypt-prod`. When debugging the HTTP-01 flow, switch the Ingress
  annotation to `letsencrypt-staging` first (unlimited retries), then back to prod — prod
  has a 5-failed-validations/hour limit.
- Edge rate limiting + security headers are Sprint 3 C3 (not configured yet).
