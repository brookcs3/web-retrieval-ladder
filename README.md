<p align="center"><img src="assets/logo-light.jpg" alt="Jina Lord: The Blocked-Fetch Retrieval Ladder" width="420"></p>

# Jina Lord: The Blocked-Fetch Retrieval Ladder

*Plugin name: `web-retrieval-ladder` (the fun name is for humans; the machine name is what fires it).*


A Claude Code plugin that turns "the fetch got blocked" into a diagnosis and a
next rung instead of a blind retry. It forks and supersedes the public
`fetching-blocked-urls` skill (the original is kept at
`skills/fetching-blocked-urls/SKILL.md.orig` for reference) and keeps the skill
name so the familiar trigger vocabulary still fires. The content is a full
rewrite around techniques proven in the field on loc.gov, archive.org, Veridian
newspaper archives, and other bot-walled sources.

Four parts:

- **`skills/fetching-blocked-urls/SKILL.md`**: the ladder, the diagnosis
  discipline, the jina header set and parse rules, the archive.org go-around,
  and the hand-off to the real-browser tier.
- **`commands/fetch-blocked.md`**: the `/fetch-blocked <url> [what to
  extract]` slash command that drives the script under the skill's rules.
- **`scripts/ladder.py`**: the instrument. `diagnose <url>` walks the rungs and
  prints one STATUS line per attempt; `fetch <url>` returns the body from the
  cheapest rung that passes. Every failure names its cause:
  `ok | EMPTY-RAW | CHALLENGE | PARSE-FAIL | BUDGET | KEY-402 | RATE-429 | TIMEOUT`.
- **`hooks/wall_detect.py`**: a PostToolUse and PostToolUseFailure hook on
  `WebFetch|Bash` that spots wall signatures in tool output and adds one
  paragraph of context naming the signature and the next command to run.

## Install

From the local checkout (the `cameron-web` marketplace lives inside the repo):

```
claude plugin marketplace add /path/to/web-retrieval-ladder
claude plugin install web-retrieval-ladder@cameron-web
```

From GitHub:

```
claude plugin marketplace add brookcs3/web-retrieval-ladder
claude plugin install web-retrieval-ladder@cameron-web
```

Validate a checkout before installing: `claude plugin validate <path>`.

## The ladder

The open web is rung 0: `WebFetch` to read, `WebSearch` to find. jina is not
for ordinary lookups; it spends metered key quota and adds failure modes the
open web does not have. Escalate only on a real wall, one rung at a time:

1. **Plain fetch with a real browser User-Agent and Accept headers.** Many 403s
   are UA-only and end here.
2. **`r.jina.ai` reader, keyed**, with the full header set on the first attempt
   (`Authorization: Bearer`, `X-Engine: browser`, `X-No-Cache: true`,
   `X-Token-Budget: 120000`), four tries with `4 + 3*i` second backoff, the
   body unwrapped after `Markdown Content:` and scrubbed of control characters
   before any JSON parse. A `"data":null` shell is a transient proxy error and
   is retried, never returned. `BudgetExceededError` means shrink the request,
   never raise the budget. A 402 (or a 401: key missing or rejected) is
   `KEY-402`.
3. **`s.jina.ai` open-web search**: a plain `POST https://s.jina.ai/` with
   `{"q": ..., "num": N}` and `X-Respond-With: no-content` (URLs, titles, and
   descriptions, no page content; the call bills a flat 10K tokens with or
   without the header, which buys speed, not tokens). No search-tool
   signature.
4. **archive.org go-around**: the availability API rate-limits per IP; when it
   429s, route the same availability URL through `r.jina.ai` and pull the
   capture from `web.archive.org`. A snapshot's existence is never the verdict,
   its content is: pull it, normalize `<br/>` to spaces, strip tags, grep; PDF
   captures go through `pdftotext`.
5. **Real-browser tier**: the `seleniumbase-stealth` plugin (`stealth_fetch`,
   `cdp_fetch`, `session_*`), only for a genuine Turnstile, PerimeterX, or
   managed-challenge wall, never for a plain lookup.

Diagnosis discipline runs through every rung: an empty result is a diagnosis,
not a throttle; change exactly one variable per retry (UA, encoding, rung,
pacing); back off seconds, not minutes; never narrate cooldowns; claim
"blocked" only when the response literally says so; and never solve a CAPTCHA
programmatically in this plugin (that is the stealth tier's explicit flow).

## The hook

`hooks/hooks.json` registers the same command hook, `hooks/wall_detect.py`
(stdlib only, ~30 ms), on two events with matcher `WebFetch|Bash` and a
10-second timeout: PostToolUse (a tool that returned) and PostToolUseFailure
(a Bash command that exited non-zero, such as `curl -f` on a 403, or a
WebFetch that threw; those arrive with an `error` string instead of a
`tool_response`). Only WebFetch and Bash are scanned whatever the matcher
says.

What counts as a wall, in order: a numeric 403/418/429 from WebFetch or an
explicit status line in the output (`HTTP/1.1 403`, `status: 403`, `"code":
403`, curl's `The requested URL returned error: 403`, a bare `403` from `-w
'%{http_code}'`); then a STRONG interstitial signature in the first 1500
characters or anywhere in a body under 4000 characters (`Just a moment`,
`Verify`/`Verifying you are human`, `Checking your browser`, `Enable
JavaScript and cookies to continue`, `Performing security verification`,
`cf-mitigated: challenge`, `cf-turnstile`, `challenges.cloudflare.com`,
`_Incapsula_`, `PerimeterX` / `_pxhc` / `px-captcha`, a reader `Title:` line
that is a block page such as `Title: Error |`); then, never on a normal-sized
2xx, a SOFT word (`403 Forbidden`, `HTTP 403/418`, `Access Denied`,
`Attention Required`, `DataDome`, `418 I'm a teapot`, `429 Too Many
Requests`, `rate limit exceeded`) only in a small body or inside a `<title>`,
`<h1>`, or reader `Title:` headline; and WebFetch's own failure wording
(`Failed to fetch`, `Unable to fetch`, ...) only for WebFetch, never for Bash.

On a hit it prints a `hookSpecificOutput.additionalContext` paragraph: the
signature, the URL when known (an `r.jina.ai/` prefix stripped), the next
command (`ladder.py diagnose <url>` then `fetch`, or `ladder.py wayback` when
the 429 came from `archive.org/wayback/available`), the one-variable rule, the
rule against re-running the identical fetch or narrating cooldowns, and the
stealth-tier boundary. On no hit it prints nothing. It always exits 0 and
swallows every exception.

Suppressions keep it quiet where it should be: a Bash command containing
`ladder.py` or `wall_detect` (the instruments print these words on purpose),
output that is already a `# STATUS:` report, Bash commands whose only tools
are git / gh / package managers (their 403s and 429s are auth and registry
limits, not web walls), and interrupted or timed-out tool calls.

## Key setup

`ladder.py` reads the jina key from, in order: the `JINA_API_KEY` environment
variable, `~/.config/jina/api_key`, then
`~/.config/jina/api_key`. The key file is the bare
token, no `KEY=` prefix. The key is never printed (not on stdout, not in a
trace, not on curl's argv); on a 402 or a 401 the STATUS line says `KEY-402`
and nothing else.

The Claude Code Bash tool runs a fresh non-interactive login zsh per call
(verified 2026-09-24: `[[ -o interactive ]]` false, `[[ -o login ]]` true), so
it never reads `~/.zshrc`; the `export JINA_API_KEY=...` line lives in
`~/.zshenv` (read by every zsh) and that is what puts the key in the tool
shell. `~/.bashrc` carries the same line for interactive bash terminals; a
`bash script.sh` started from the tool shell inherits the export from its zsh
parent, while a bare `env -i bash -c` sees nothing (non-interactive bash reads
no rc file). An export made in one Bash call does not survive to the next.
`JINA_API_KEY_FILE=<path>` makes `ladder.py` read one named key file instead
of the default list (`/dev/null` runs keyless on purpose).

Balance check (the key stays in the environment, never in the transcript):

```
curl -s -H "Authorization: Bearer $JINA_API_KEY" \
  "https://embeddings-dashboard-api.jina.ai/api/v1/api_key/user?api_key=$JINA_API_KEY" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["wallet"]["total_balance"])'
```

## Layout

```
.claude-plugin/plugin.json          manifest (no MCP servers; the browser tier is a separate plugin)
.claude-plugin/marketplace.json     local marketplace entry (cameron-web)
commands/fetch-blocked.md           the /fetch-blocked slash command
hooks/hooks.json                    PostToolUse + PostToolUseFailure registration
hooks/wall_detect.py                the wall-signature detector
scripts/ladder.py                   the instrument (fetch / search / wayback / health / diagnose)
skills/fetching-blocked-urls/       the skill (SKILL.md), its README and CHANGELOG, and the original (SKILL.md.orig)
```

## Related

- `seleniumbase-stealth` (cameron-local marketplace): the real-browser rung
  this plugin escalates to. Its scope clause: reserved for walled archives that
  need it; a plain search or an unwalled page never goes through it.
