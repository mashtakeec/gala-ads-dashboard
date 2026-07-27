# Git — Deploy Author

This repo deploys to Vercel via the **mashtakeec** GitHub account (Hobby plan).
Vercel only auto-deploys commits authored by the repo owner.

**Every git commit in this repo MUST use:**

```
--author="mashtakeec <mashtakeec@gmail.com>"
```

This applies regardless of which local git user is configured (e.g. danidevmash).
Never commit with any other author — it will break the Vercel deploy.
