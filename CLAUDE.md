# Git — Deploy Author

This repo deploys to Vercel via the **mashtakeec** GitHub account (Hobby plan).
Vercel only auto-deploys commits authored by the repo owner.

**Every git commit in this repo MUST use:**

```
--author="mashtakeec <mashtakeec@gmail.com>"
```

This applies regardless of which local git user is configured (e.g. danidevmash).
Never commit with any other author — it will break the Vercel deploy.

---

## Workflow: Claude Desktop + Claude Code

Claude Desktop connects to GitHub via the MCP Contents API, which **always stamps the authenticated user (danidevmash) as author** — this cannot be overridden. Commits from danidevmash will NOT trigger a Vercel deploy.

### If you are Claude Desktop (MCP / GitHub Contents API):
- **DO NOT push or commit directly to this repo.** Your commits will be authored as danidevmash and Vercel will ignore them.
- Instead, save the updated `index.html` as a local file (e.g. `index_MMDD.html`) in `E:\Work\Gala Resort\GALA Ads Dashboard\` and tell the user to hand it to Claude Code for commit + push.

### If you are Claude Code (CLI / git):
- You have full git CLI access. Always commit with `--author="mashtakeec <mashtakeec@gmail.com>"`.
- When the user hands you an updated file from Claude Desktop, copy it into the repo, commit, and push.
