# Jina Lord: The Blocked-Fetch Retrieval Ladder

The web-retrieval ladder as a skill: five rungs from the open web to a real
browser (WebFetch, browser-UA curl, the keyed `r.jina.ai` reader, `s.jina.ai`
search, the archive.org go-around, then a handoff to `seleniumbase-stealth`),
with a STATUS-line diagnosis discipline so an empty result is read as a cause,
not a throttle. Forked from and superseding oaustegard's
`fetching-blocked-urls` 0.1.1 (a single-rung jina wrapper, kept at
`SKILL.md.orig`).

Reach for it on a wall signal (403, 418, "Just a moment", Turnstile,
PerimeterX, an empty body, an SPA shell, a paywall soft-block, an archive.org
429). Not for ordinary lookups: WebSearch and WebFetch come first.

One command:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ladder.py" fetch "https://www.hmdb.org/m.asp?m=1"
```

or, without the script, the keyed reader rung on its own (the exact header set
that passes the loc.gov and hmdb walls):

```bash
curl -s --max-time 90 -H "Authorization: Bearer $JINA_API_KEY" -H "X-Engine: browser" \
  -H "X-No-Cache: true" -H "X-Token-Budget: 120000" "https://r.jina.ai/https://www.hmdb.org/m.asp?m=1"
```

Key: `JINA_API_KEY` from the environment, else `~/.config/jina/api_key`; never printed. Slash command:
`/fetch-blocked <url> [what to extract]`.
