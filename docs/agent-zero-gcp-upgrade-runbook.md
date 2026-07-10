# Agent Zero — GCP Upgrade Runbook

**Project:** agent-zero-vps-2026
**Maintainer:** Jokerrwild
**Last Updated:** 2026-07-10
**GCP Console:** https://console.cloud.google.com/compute/instances?project=agent-zero-vps-2026

---

## Overview

This runbook documents the standard procedure for upgrading the Agent Zero framework running on Google Cloud Platform. The architecture uses a Container-Optimized OS (COS) VM that pulls and runs Agent Zero as a Docker container on startup. Upgrades are performed by creating a new Instance Template with the updated image tag, then spinning up a new VM from that template.

> **Do not attempt to upgrade in-place on a running VM.** Always create a new template and a new VM. This ensures a clean, reproducible deployment and preserves the ability to roll back.

---

## Architecture Summary

| Component | Value |
|---|---|
| GCP Project | `agent-zero-vps-2026` |
| Region | `us-central1` |
| Machine Type | `e2-standard-4` (4 vCPU, 16 GB RAM) |
| OS | Container-Optimized OS (COS) |
| Boot Disk | 30 GB Balanced Persistent Disk |
| Docker Image | `docker.io/agent0ai/agent-zero:latest` |
| Container Name | `agent-zero-main` |
| Port | `80` (HTTP) |
| Data Volume | `/mnt/stateful_partition/agent-data` -> `/a0` |
| Firewall | HTTP + HTTPS open (`http-server`, `https-server` tags) |

---

## Instance Template Inventory

| Template Name | Image Tag | Created | Notes |
|---|---|---|---|
| `agent-zero-latest-template` | `latest` | 2026-05-24 | **Current active template** |
| `agent-zero-v1-15-template` | `v1.15` | 2026-05-22 | Previous version |
| `agent-zero-v1-15-template-20260523-164617` | `v1.15` | 2026-05-23 | Dated backup copy |
| `agent-zero-v1-8-definitive-template` | `v1.8` | 2026-04-12 | Older stable version |
| `sentry-0-final-v7-16gb` | `cos-stable` | 2026-03-20 | Watcher/sentry VM |

---

## Snapshot Inventory

| Snapshot Name | Source Disk | Size | Type | Date | Purpose |
|---|---|---|---|---|---|
| `agent-zero-data-...` | `agent-zero-data` | 665 KB | Scheduled | Mar 7, 2026 | `/a0` data volume backup |
| `agent-zero-v0-9-8-final-snapshot` | `sentry-0-watcher-group-hsqz` | 793 MB | Manual | Apr 12, 2026 | Full disk snapshot |
| `agent-zero-vps-...` x2 | `agent-zero-vps` | ~4 GB | Scheduled | Mar 2026 | Periodic VPS backups |
| `macready04122026` | `sentry-0-watcher-group-hsqz` | 5.92 GB | Manual | Apr 12, 2026 | Full machine snapshot |

---

## Upgrade Procedure

### When to Upgrade

- A new Agent Zero version is released on Docker Hub (`agent0ai/agent-zero`)
- You want to pull a specific pinned version (e.g., `v0.9.8`)
- The current VM is unhealthy or the VPS crashed
- You are rebuilding after data loss

---

### Step 1 — Check the Current Running Version

Before upgrading, confirm what is currently running.

1. Go to **GCP Console > Compute Engine > VM Instances**
2. Identify the active `agent-zero-main` VM
3. Note the **External IP** address
4. Open `http://<EXTERNAL_IP>` in your browser
5. In Agent Zero UI, go to **Settings** and note the current version displayed

Alternatively, SSH into the VM and run:

```bash
docker inspect agent-zero-main | grep Image
```

---

### Step 2 — Check Docker Hub for the Latest Version

1. Go to https://hub.docker.com/r/agent0ai/agent-zero/tags
2. Identify the latest stable tag (e.g., `latest`, or a pinned version like `v0.9.9`)
3. Decide whether to use `latest` (always pulls newest) or a pinned version tag

> **Recommendation:** Use `latest` for the active template unless you need to pin to a specific version for stability testing.

---

### Step 3 — Take a Snapshot of the Current VM (Safety Net)

Before making any changes, snapshot the current disk to preserve any agent data.

1. Go to **GCP Console > Compute Engine > Snapshots**
2. Click **Create Snapshot**
3. Set:
   - **Name:** `agent-zero-pre-upgrade-YYYYMMDD` (e.g., `agent-zero-pre-upgrade-20260710`)
   - **Source disk:** select the current `agent-zero-main` boot disk
   - **Location:** Regional
4. Click **Create**
5. Wait for the snapshot status to show **Ready**

---

### Step 4 — Create a New Instance Template

Do not modify the existing template. Always create a new one.

1. Go to **GCP Console > Compute Engine > Instance Templates**
2. Click on `agent-zero-latest-template` (or the most recent active template)
3. Click **Create Similar** at the top
4. Update the **Name** field:
   - Format: `agent-zero-YYYYMMDD-template`
   - Example: `agent-zero-20260710-template`
5. Scroll down to **Advanced Options > Management > Startup Script**
6. Locate the two lines referencing the Docker image tag and update both:

```bash
# BEFORE (example — v1.15)
docker pull docker.io/agent0ai/agent-zero:v1.15
...
docker.io/agent0ai/agent-zero:v1.15

# AFTER (update to latest or specific new version)
docker pull docker.io/agent0ai/agent-zero:latest
...
docker.io/agent0ai/agent-zero:latest
```

7. Also update the echo message in the script to reflect the new version:

```bash
echo "[DEPLOY] Starting Agent Zero latest deployment"
...
echo "[DEPLOY] Agent Zero latest deployment complete"
```

8. All other settings remain unchanged:
   - Machine type: `e2-standard-4`
   - Disk: 30 GB balanced persistent
   - Firewall: HTTP + HTTPS checked
   - Volume mount: `/mnt/stateful_partition/agent-data:/a0`
   - Port: `80:80`

9. Click **Create**

---

### Step 5 — Create a New VM from the New Template

1. Go to **GCP Console > Compute Engine > Instance Templates**
2. Click on the new template you just created
3. Click **Create VM** at the top
4. Set:
   - **Name:** `agent-zero-main` (or date-stamped: `agent-zero-main-20260710`)
   - **Region/Zone:** `us-central1` / `us-central1-a`
   - All other settings are pre-filled from the template — do not change them
5. Dismiss any informational popups
6. Click **Create**

---

### Step 6 — Monitor Startup

The VM goes through three phases after creation:

| Phase | What Is Happening | Expected Error If You Browse Too Early |
|---|---|---|
| Phase 1: VM Provisioning | GCP allocates hardware, boots COS | `ERR_CONNECTION_TIMED_OUT` |
| Phase 2: Docker Pull | COS pulls the Agent Zero image from Docker Hub (~2-4 min) | `ERR_CONNECTION_REFUSED` |
| Phase 3: Container Start | Docker starts the container, supervisord launches the UI | Brief loading, then the UI appears |

**To monitor:**

1. In **VM Instances**, wait for the status circle to turn **green**
2. Note the **External IP** assigned to the new VM
3. Open `http://<NEW_EXTERNAL_IP>` in your browser
4. If you see `ERR_CONNECTION_REFUSED`, wait 60-90 seconds and refresh — Docker is still pulling
5. The VM is healthy when the Agent Zero welcome/onboarding screen loads

**To check startup logs via SSH:**

```bash
# SSH into the VM from GCP Console > VM Instances > SSH button
sudo journalctl -u google-startup-scripts -f

# Or check Docker container status
docker ps
docker logs agent-zero-main --tail 50
```

---

### Step 7 — Verify Agent Zero is Healthy

Once the UI loads, confirm the following:

- [ ] Agent Zero welcome screen or chat interface is visible at `http://<EXTERNAL_IP>`
- [ ] Settings page shows the expected new version
- [ ] Model provider is configured (API key is set)
- [ ] A test prompt returns a valid response
- [ ] No error banners are displayed in the UI

---

### Step 8 — Stop or Delete the Old VM

Once the new VM is confirmed healthy:

1. Go to **GCP Console > Compute Engine > VM Instances**
2. Select the old `agent-zero-main` VM
3. Click **Stop** (keeps the disk for reference) or **Delete** (removes it entirely)

> **Recommendation:** Stop first, verify for 24 hours, then delete. This avoids double-billing for compute while retaining the option to restart the old VM if something goes wrong.

---

## Full Startup Script Reference

This is the complete startup script used in `agent-zero-latest-template`. Copy this exactly when creating new templates — only change the image tag.

```yaml
#cloud-config
bootcmd:
  - mkdir -p /mnt/stateful_partition/agent-data
  - chmod -R 777 /mnt/stateful_partition/agent-data
runcmd:
  - |
    set -e
    echo "[DEPLOY] Starting Agent Zero latest deployment"
    # Step A: Stop and remove the old container
    docker stop agent-zero-main || true
    docker rm agent-zero-main || true
    # Step B: Pull the latest image
    docker pull docker.io/agent0ai/agent-zero:latest
    # Step C: Launch container
    docker run -d --name agent-zero-main \
      -p 80:80 \
      -v /mnt/stateful_partition/agent-data:/a0 \
      --restart always \
      -e HOST=0.0.0.0 -e PORT=80 \
      docker.io/agent0ai/agent-zero:latest
    # Step D: Wait for startup and restart UI
    sleep 30
    docker exec agent-zero-main supervisorctl restart run_ui || true
    echo "[DEPLOY] Agent Zero latest deployment complete"
```

---

## Rollback Procedure

If the new VM is unhealthy after upgrade:

1. **Stop the new VM** — GCP Console > VM Instances > Stop
2. **Restart the old VM** (if you stopped rather than deleted it) — click Start/Resume
3. If the old VM was deleted, create a new VM from the previous template (e.g., `agent-zero-v1-15-template`)
4. If data was lost, restore from the pre-upgrade snapshot:
   - GCP Console > Compute Engine > Snapshots
   - Select the snapshot > Click **Create Disk**
   - Attach the restored disk to a new VM

---

## Recovery Procedure (VPS Crash / Total Loss)

If both the VM and disk are gone:

1. Go to **GCP Console > Compute Engine > Instance Templates**
2. Select `agent-zero-latest-template`
3. Click **Create VM**
4. Name it `agent-zero-main`
5. Click **Create**
6. Monitor startup per Step 6 above
7. Once healthy, reconfigure your model provider API keys in Agent Zero Settings
8. Restore any backed-up agent data from the most recent snapshot if available

> **Note:** The `/a0` volume on a fresh VM will be empty. Agent Zero will initialize a clean state. API keys and model configuration must be re-entered via the Settings UI.

---

## Quick Reference Checklist

```
PRE-UPGRADE
[ ] Check current version in Agent Zero Settings
[ ] Check Docker Hub for new version tag
[ ] Take a snapshot of current VM disk

UPGRADE
[ ] Create new Instance Template (Create Similar from current)
[ ] Update image tag in startup script (both pull and run lines)
[ ] Name template with date: agent-zero-YYYYMMDD-template
[ ] Create VM from new template, name it agent-zero-main
[ ] Monitor: green status -> external IP -> browser test
[ ] Confirm UI loads and version is correct

POST-UPGRADE
[ ] Stop (not delete) old VM for 24 hours
[ ] Verify model provider API keys are working
[ ] Run a test prompt
[ ] Delete old VM once confirmed healthy
[ ] Update this runbook with new template name and date
```

---

## Key Links

| Resource | URL |
|---|---|
| GCP Console | https://console.cloud.google.com/compute/instances?project=agent-zero-vps-2026 |
| Instance Templates | https://console.cloud.google.com/compute/instanceTemplates/list?project=agent-zero-vps-2026 |
| Snapshots | https://console.cloud.google.com/compute/snapshots?project=agent-zero-vps-2026 |
| Docker Hub (Agent Zero) | https://hub.docker.com/r/agent0ai/agent-zero/tags |
| Agent Zero GitHub Releases | https://github.com/agent0ai/agent-zero/releases |
| Agent Zero UI (current) | http://34.9.112.244 |

---

*Maintained by Jokerrwild | Market_Analysis/docs | Last verified: 2026-05-24*
