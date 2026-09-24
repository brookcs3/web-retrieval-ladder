# fetching-blocked-urls - Changelog

All notable changes to the `fetching-blocked-urls` skill are documented in
this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions track the skill; the plugin `web-retrieval-ladder` carries its own.

## [1.0.1] - 2026-09-24

### Changed

- Named the plugin "Jina Lord: The Blocked-Fetch Retrieval Ladder"; added the logo (assets/).

## [1.0.0] - 2026-09-24

Forked from oaustegard `fetching-blocked-urls` 0.1.1 (2026-01-27) and
rewritten in full around the Project Seal retrieval stack (2026-07-13 to
2026-08-16), re-verified live on 2026-09-24. The skill name is kept for its
trigger vocabulary; the body is new. The original is kept as `SKILL.md.orig`.

### Added

- The five-rung ladder with an exact command per rung: WebSearch/WebFetch
  (rung 0), browser-UA curl with Accept headers and `-L` (rung 1), the keyed
  `r.jina.ai` reader (rung 2), `s.jina.ai` POST search with
  `X-Respond-With: no-content` (rung 3), the archive.org availability
  go-around through the reader plus CDX plus pull-and-grep with `pdftotext`
  for PDF captures (rung 4), and the handoff to `seleniumbase-stealth`
  (rung 5).
- The exact rung-2 header set on the FIRST attempt: `Authorization: Bearer`,
  `X-Engine: browser`, `X-No-Cache: true`, `X-Token-Budget: 120000`.
- Retry policy: 4 attempts, `4 + 3*i` seconds backoff, in a loop that runs
  in both zsh and bash.
- Parse rules: unwrap after `Markdown Content:`; scrub control characters
  `[\x00-\x08\x0b\x0c\x0e-\x1f]` before any JSON parse; `"data":null` in the
  first 200 bytes is a proxy error (409 `BudgetExceededError` checked first,
  then the transient 422 `TimeoutError`, then the 422 selector miss).
- Request shrinking on BUDGET: `&at=results,pagination` for JSON,
  `X-Target-Selector` for HTML; never raise the budget.
- The STATUS-line triage table: `ok | EMPTY-RAW | CHALLENGE | PARSE-FAIL |
  BUDGET | KEY-402 | RATE-429 | TIMEOUT`, with the action for each.
- The diagnosis discipline: an empty result is a diagnosis, one variable per
  retry, one call at a time, no cooldown narration, "blocked" only when the
  response says so, a 200 is not a verdict, no CAPTCHA solving here.
- Key handling: lookup order (environment, `~/.config/jina/api_key`,
  `Project-Seal/jngaapi.txt`), never printed, the `~/.zshenv` note for the
  Claude Code Bash tool, the per-call fresh-shell note, and the balance
  endpoint (`health`).
- Gotchas: italics rendered as underscores mid-string, the cache and
  challenge `Warning:` tells, OCR line wraps, index thinness (the old
  curl-vs-browser "two-instrument gap" retired), binary captures.
- The wall-signal table (403 UA-only vs fingerprint, 418, Turnstile
  interstitials, soft-block 200s, SPA shells, archive.org 429, 402) mapped to
  the first rung to try.
- The selenium scope clause and the stealth tool table for the rung-5
  handoff.
- Limits stated plainly, including which sites the reader does and does not
  pass (verified 2026-09-24).
- The `/fetch-blocked <url> [what to extract]` command driving
  `scripts/ladder.py` (`fetch`, `search`, `wayback`, `health`, `diagnose`).

### Changed

- Trigger policy: 0.1.1 said "invoke immediately" on any 403, timeout, or
  empty content. 1.0.0 puts WebSearch/WebFetch first (the rung 0 law) and
  starts only at a real wall signal.
- The core command: the anonymous-or-keyed `${JINA_API_KEY:+-H}` split is
  gone; the reader call is always keyed with the four headers, and the key
  comes from a three-place lookup instead of `~/.zshrc`.
- Retry: 3 attempts with a 1 s sleep on `upstream connect error` became 4
  attempts with `4 + 3*i` s on `"data":null` or a challenge, with the browser
  engine on the first attempt rather than on retry.
- Escalation: "request user assistance after retry exhaustion" became the
  archive.org go-around and the seleniumbase-stealth handoff, then a plain
  report of what was tried.
- Output-format note kept, extended with the optional `Published Time:` and
  `Warning:` lines.

### Removed

- The "~10% intermittent failures" rationale and the `upstream connect error`
  grep (replaced by the observed 409/422/402/429 shapes).
- "`r.jina.ai` is whitelisted in Claude container network configuration"
  (not applicable to local Claude Code).

### Corrected in the same-day adversarial review (2026-09-24)

- UDN moved from a rung-5 ground to a rung-2 pass: its 418 walls curl, the
  keyed reader returns the search and details pages.
- The `Warning:` lines are cache tells, not anonymous-tier tells (one
  appeared on a keyed call); the keyed tier's measurable difference is the
  rate limit, 500/min vs 20/min (`x-ratelimit-limit`).
- The "curl 3 vs browser 37" two-instrument gap retired: every channel
  returned the same total on the same query, and the memory had already
  corrected it on 2026-07-19.
- `s.jina.ai` bills a flat 10,000 per call with or without
  `X-Respond-With: no-content`; the header buys speed and payload.
- The rung-4 worked example now uses a URL with a real OCR-bearing capture
  (the UMFRIED case), truncates the capture file before the pull, pulls the
  raw `id_` capture over https, and gates the grep on the HTTP code (a failed
  pull left the previous run's bytes behind under zsh; a 404 page grepped as
  "clear").
- The retry loop defines its own `U` (every Bash tool call is a fresh shell).
- `X-Return-Format` documented (`text` drops the header block; `html` is the
  raw page); the `x-usage-tokens` and `x-ratelimit-*` response headers noted;
  the dashboard balance noted as lagging.
- The `ladder.py` section rewritten against the shipped script: `--rung
  1|2|5`, `--selector`, `--format`, `--out`, `--max-chars`, `--timeout`,
  `JINA_API_KEY_FILE`, the STATUS-first output contract for every subcommand,
  `wayback`'s `VERDICT:` lines, `KEY-402` covering 401, `PARSE-FAIL` with
  `rung=-` for an internal error.
- The bash note corrected: `~/.zshenv` is what puts the key in the tool shell
  (a non-interactive login zsh); `~/.bashrc` serves interactive bash only,
  and a bash child of the tool shell inherits the export.
- The description frontmatter widened (bot check, CAPTCHA, any 429, the
  WebFetch failure wording, UDN).
- Every bash block run under bash 3.2 and zsh 5.9 against live URLs.

## [0.1.1] - 2026-01-27 (upstream)

- Add/Update skill: fetching-blocked-urls (oaustegard).
