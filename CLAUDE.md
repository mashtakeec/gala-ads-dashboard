# Git — Deploy

This repo deploys to Vercel via a **Deploy Hook** triggered by a GitHub Action on every push to `main`.
Any user (mashtakeec or danidevmash) can push — the Action triggers the deploy regardless of commit author.

## For Claude Desktop (MCP / GitHub Contents API)
- You can push directly to this repo. The GitHub Action will trigger the Vercel deploy automatically.
- No special `--author` flag is needed.

## For Claude Code (CLI / git)
- Commit and push normally. The GitHub Action handles the deploy.
- Preferred author for consistency: `--author="mashtakeec <mashtakeec@gmail.com>"`
