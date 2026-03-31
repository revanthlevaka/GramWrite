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
