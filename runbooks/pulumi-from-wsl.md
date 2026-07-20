# Running Pulumi infra from WSL (Smart App Control workaround)

Why the infra applies run from WSL Ubuntu instead of Windows, and how to set it up / use it.

## The problem

Windows 11 **Smart App Control (SAC)** is enabled on this machine (`HKLM:\SYSTEM\
CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1`, Enforced). SAC
blocks unsigned/unrecognized executables and has **no per-app allow-list**. Pulumi's
`azure-native` resource plugin is a large **unsigned** binary
(`~/.pulumi/plugins/resource-azure-native-*/pulumi-resource-azure-native.exe`, ~600 MB),
so `pulumi preview` / `pulumi up` on Windows fails with:

```
error: failed to load plugin ...pulumi-resource-azure-native.exe:
  ... An Application Control policy has blocked this file.
```

**Do not turn SAC off to fix this** — SAC is a one-way switch (it cannot be re-enabled
without a clean Windows reinstall) and disabling it is a real security downgrade.

## The fix

SAC only governs **Windows** executables, not Linux binaries under WSL2. So run all
Pulumi/Azure infra work from **WSL Ubuntu**, where the Linux `pulumi-resource-azure-native`
loads freely. SAC stays on.

## One-time setup (done 2026-07-20)

In an Ubuntu (WSL) terminal:

1. Install Azure CLI + Pulumi (a helper script does this; see
   `scratchpad/wsl-infra-setup.sh` if regenerating). Essentials:
   ```bash
   sudo apt-get update -y && sudo apt-get install -y curl unzip ca-certificates
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash      # az (arm64: pip venv fallback)
   curl -fsSL https://get.pulumi.com | sh                      # pulumi -> ~/.pulumi/bin
   echo 'export PATH="$HOME/.pulumi/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
   ```
2. **Azure login — target the subscription's tenant directly.** A blanket `az login`
   bounces off MFA/security-defaults across the other tenants and finds no subscription.
   The CanI subscription lives in the **Default Directory** tenant:
   ```bash
   az login --use-device-code --tenant ddb3853e-a709-42c4-8841-8e69da7a1c45
   az account show    # expect subscription id 6591cee6-ee26-4155-ae71-3777bf7e9c73, Enabled
   ```
3. **Pulumi login** — paste a Personal Access Token from
   https://app.pulumi.com/account/tokens (labelled e.g. `cani-wsl`). Connects WSL to the
   same `jasonbrookecarney-gmail-com` backend the Windows CLI used.
   ```bash
   pulumi login
   pulumi whoami      # expect jasonbrookecarney-gmail-com
   ```

Verified 2026-07-20: `azure-native` v3.20.0 plugin installs/loads in WSL with no
Application Control error (the exact binary SAC blocks on Windows).

## Python venv (per infra project — NOT on OneDrive)

The infra projects are Python Pulumi (`runtime: python`, `virtualenv: venv`). The repo lives
on a OneDrive-synced path (`/mnt/c/Users/jason/OneDrive/...`); do **not** create the venv
there — a venv is thousands of files OneDrive will churn on and can lock mid-run. The Windows
`venv/` in each infra project is dead (Windows Pulumi is SAC-blocked) and can be ignored.

Preferred: keep the venv off the synced tree. Two working options:
- **WSL-native repo clone** for infra work (`git clone` into `~/CanI`), or
- point `virtualenv` at a WSL-native path.

(TODO: settle this at the start of the D1 session; the SAC block itself is already solved —
this is only about where the Python deps live for `pulumi up`.)

## Running infra going forward

From Windows (Git Bash / PowerShell) you can drive WSL directly:

```bash
wsl -d Ubuntu -- bash -lc 'export PATH="$HOME/.pulumi/bin:$PATH"; \
  cd /mnt/c/Users/jason/OneDrive/Documents/Work/CanI/infra/platform && \
  pulumi preview --stack dev'
```

Or open an Ubuntu terminal and run `pulumi` directly from the project dir. The
`kubectl` / `az aks command invoke` cluster operations are unaffected by SAC and can still
run from either Windows or WSL.

## Key facts

- Subscription: `6591cee6-ee26-4155-ae71-3777bf7e9c73` ("Default"), tenant
  `ddb3853e-a709-42c4-8841-8e69da7a1c45` (Default Directory), user
  `jasonbrookecarney@outlook.com`.
- Pulumi org/backend: `jasonbrookecarney-gmail-com` (Pulumi Cloud). Stacks:
  `cani-platform/dev`, `cani-workload/dev`.
- WSL distro: Ubuntu 26.04 LTS, arm64 (this is a Windows-on-ARM machine).
- Alternative to WSL (better long-term): infra applies via CI (GitHub Actions Linux runner +
  Azure OIDC federated credentials) — removes the laptop from the apply path entirely.
