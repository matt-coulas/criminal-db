# Publish Docker images with GitHub Actions

This guide walks you through publishing **criminal-db** container images from GitHub Actions—no manual `docker push` on your laptop required after setup.

The repo includes two workflows:

| Workflow file | Registry | Secrets required |
|---------------|----------|------------------|
| [`.github/workflows/docker-publish-ghcr.yml`](../.github/workflows/docker-publish-ghcr.yml) | [GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) | None (uses built-in `GITHUB_TOKEN`) |
| [`.github/workflows/docker-publish-dockerhub.yml`](../.github/workflows/docker-publish-dockerhub.yml) | [Docker Hub](https://hub.docker.com) | `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` |

Start with **GHCR** only; add Docker Hub when you want images on both registries.

---

## What gets published

- **Image contents:** application code + Python deps (`embed`, `pdf`, `tui` extras)—see [Dockerfile](../Dockerfile).
- **Not included:** `data/`, `db/`, or your case corpus (mount those at runtime).

**Triggers:**

| Event | GHCR / Hub tags (examples) |
|-------|----------------------------|
| Push to `main` | `latest`, `main-sha-abc1234` |
| Push tag `v0.3.0` | `0.3.0`, `0.3`, `latest` (if also on main—tags use semver rules) |
| **Actions → Run workflow** | Same as above for the selected ref |

---

## Part 1 — GHCR (recommended first)

### Step 1: Confirm workflows are on your branch

Merge or push so `.github/workflows/docker-publish-ghcr.yml` exists on `main`.

### Step 2: No registry secrets needed

GHCR uses the automatic **`GITHUB_TOKEN`** for the workflow run. The workflow already requests:

```yaml
permissions:
  packages: write
```

You do **not** add `GITHUB_TOKEN` under Settings → Secrets.

### Step 3: Run the workflow

**Option A — push to main**

```bash
git push origin main
```

**Option B — version release**

```bash
git tag v0.3.0
git push origin v0.3.0
```

**Option C — manual**

1. GitHub → **Actions** → **Publish Docker image (GHCR)** → **Run workflow** → choose branch → **Run workflow**.

### Step 4: Watch the run

1. **Actions** tab → click the latest run.
2. Open job **build-and-push** → step **Build and push** should succeed.

### Step 5: Find the image

1. GitHub repo → **Packages** (right sidebar) → **criminal-db** (or under your profile **Packages**).
2. Image name:

   `ghcr.io/<owner>/criminal-db:<tag>`

   For this repo: `ghcr.io/matt-coulas/criminal-db:latest` (replace owner if you forked).

### Step 6: Make the package public (optional)

Private by default for personal repos.

1. Open the package → **Package settings** → **Change visibility** → **Public** (if you want anonymous `docker pull`).

### Step 7: Pull and run

```bash
docker pull ghcr.io/OWNER/criminal-db:latest

docker run --rm -p 8765:8765 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/db:/app/db" \
  -v "$(pwd)/models:/app/models" \
  ghcr.io/OWNER/criminal-db:latest
```

Or in `compose.yaml`:

```yaml
services:
  api:
    image: ghcr.io/OWNER/criminal-db:latest
    # remove build: . when using a published image
```

---

## Part 2 — Docker Hub (optional)

Use this if you want `docker pull youruser/criminal-db:latest` on Docker Hub.

### Step 1: Create a Docker Hub repository

1. [hub.docker.com](https://hub.docker.com) → **Create repository**.
2. Name: `criminal-db` (or match the workflow: `USERNAME/criminal-db`).

### Step 2: Create an access token

1. **Account settings** → **Security** → **New Access Token**.
2. Scope: **Read, Write, Delete** (or Read & Write).
3. Copy the token once (you will not see it again).

### Step 3: Add GitHub repository secrets

1. Repo → **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret**:

   | Name | Value |
   |------|--------|
   | `DOCKERHUB_USERNAME` | Your Docker Hub username |
   | `DOCKERHUB_TOKEN` | The access token (not your account password) |

Secrets are encrypted; they are not visible in logs when used by `docker/login-action`.

### Step 4: Enable the workflow

The file `.github/workflows/docker-publish-dockerhub.yml` is already in the repo. After secrets exist, the next push to `main` or tag `v*` will build and push to:

`docker.io/<DOCKERHUB_USERNAME>/criminal-db:latest`

### Step 5: Verify

**Actions** → **Publish Docker image (Docker Hub)** → successful run.

On Docker Hub, open your repository → **Tags** → you should see `latest` and/or version tags.

---

## Part 3 — Use both registries

You can run **both** workflows on every push:

- `ghcr.io/OWNER/criminal-db:latest`
- `docker.io/DOCKERHUB_USERNAME/criminal-db:latest`

Pin production to a version tag, not only `latest`:

```yaml
image: ghcr.io/OWNER/criminal-db:0.3.0
```

---

## Customizing triggers

Edit the `on:` block in the workflow YAML.

**Only on release tags:**

```yaml
on:
  push:
    tags: ["v*"]
  workflow_dispatch:
```

**Nightly build (in addition to main):**

```yaml
on:
  schedule:
    - cron: "0 6 * * *"   # 06:00 UTC daily
  workflow_dispatch:
```

**Disable automatic pushes** (manual only):

```yaml
on:
  workflow_dispatch:
```

---

## Troubleshooting

| Problem | What to check |
|---------|----------------|
| `denied: permission_denied` on GHCR | Workflow has `permissions: packages: write`; default branch workflow file is on GitHub |
| Docker Hub login fails | Secret names exactly `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`; token not expired |
| Package not visible | Repo **Packages** tab; first successful push creates the package |
| `403` pulling private GHCR image | `docker login ghcr.io` with PAT (`read:packages`) or make package public |
| Build slow every time | Workflow uses GHA cache; second run should be faster |
| Wrong image name on Hub | Workflow uses `${{ secrets.DOCKERHUB_USERNAME }}/criminal-db` — create that repo on Hub |

### Pull private GHCR from a server

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
docker pull ghcr.io/OWNER/criminal-db:latest
```

Use a fine-grained PAT with **read** access to packages, or classic PAT with `read:packages`.

---

## Security notes

- Do not commit corpus files, `.env` with tokens, or `db/*.db` to git.
- Do not add `GITHUB_TOKEN` as a custom secret; the built-in token is scoped to the workflow run.
- Rotate `DOCKERHUB_TOKEN` if leaked.
- The image build context is the repo root; `.dockerignore` excludes `data/` and `db/`.

---

## Related docs

- [DOCKER.md](DOCKER.md) — local build, Compose, volumes
- [COPYRIGHT_AND_REDISTRIBUTION.md](COPYRIGHT_AND_REDISTRIBUTION.md) — do not ship copyrighted corpus in the image
