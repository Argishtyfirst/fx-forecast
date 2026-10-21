#!/usr/bin/env sh
# Vercel build step ([tool.vercel.scripts] build in pyproject.toml): build the dashboard
# into backend/public/, which Vercel serves from its CDN in front of the API function.
set -eu
cd "$(dirname "$0")/../../frontend"
npm ci --no-audit --no-fund
npm run build
rm -rf ../backend/public
cp -R dist ../backend/public
