# GramWrite — GitHub Deployment Guide

## One-time setup

```bash
cd gramwrite

# Initialize git
git init
git branch -M main

# Add all files
git add .
git commit -m "feat: GramWrite v1.2.0 — initial release"

# Create repo on GitHub (requires gh CLI)
gh repo create gramwrite --public --description "The Invisible Editor for Screenwriters" --push

# OR manually:
# 1. Create repo at https://github.com/new
# 2. Then:
git remote add origin https://github.com/revanthlevaka/gramwrite.git
git push -u origin main
```

## GitHub Releases (attach installable zips)

```bash
# Tag the release
git tag -a v1.2.0 -m "GramWrite v1.2.0 — initial release"
git push origin v1.2.0

# Create release with gh CLI
gh release create v1.2.0 \
  --title "GramWrite v1.2.0" \
  --notes-file MANIFESTO.md \
  --latest
```

## Deploy landing page (GitHub Pages)

```bash
# Option A: deploy index.html from main branch /docs folder
mkdir docs
cp index.html docs/index.html
git add docs/
git commit -m "docs: add GitHub Pages landing page"
git push

# Then in GitHub: Settings → Pages → Source: main /docs

# Option B: deploy via gh-pages branch
git checkout --orphan gh-pages
git reset --hard
cp /path/to/gramwrite/index.html index.html
git add index.html
git commit -m "deploy: landing page"
git push origin gh-pages
git checkout main
```

## PyPI publish (optional)

```bash
pip install build twine
python -m build
twine upload dist/*
# Users can then: pip install gramwrite
```

## Container/CI Dependencies

When running GramWrite in a headless container or CI environment, the Qt-based UI requires several system libraries that are not included in minimal base images. Without these, you'll see errors like:

```
qt.qpa.plugin: Could not load the Qt platform plugin "xcb"
```

### Required System Packages (Debian/Ubuntu)

```dockerfile
FROM python:3.12-slim

# Install Qt/X11 runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 \
    libgl1 \
    libxkbcommon0 \
    libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*

# Install GramWrite
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "-m", "gramwrite"]
```

### Package Descriptions

| Package | Purpose |
|---------|---------|
| `libegl1` | EGL display library (Qt platform plugin) |
| `libgl1` | OpenGL library (hardware acceleration) |
| `libxkbcommon0` | Keyboard layout handling |
| `libxcb-cursor0` | X11 cursor support for Qt xcb plugin |

### Headless Mode

For CI pipelines that don't need the UI, set the `QT_QPA_PLATFORM` environment variable:

```bash
export QT_QPA_PLATFORM=offscreen
python -m gramwrite
```
