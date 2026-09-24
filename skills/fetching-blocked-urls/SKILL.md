---
name: fetching-blocked-urls
description: >-
  Use when a page fetch fails on a WALL rather than a normal error: a 403 or
  418, "Just a moment...", "Verify you are human", Cloudflare Turnstile,
  PerimeterX, a managed challenge, a bot check or CAPTCHA page, a 429 rate
  limit, a WebFetch "fetch failed" or "Unable to fetch", an empty or
  suspiciously short body, a JS-rendered SPA that returns only a shell, a
  paywall soft-block, a loc.gov, hmdb, or UDN 403/418, or an archive.org /
  wayback 429. Also use when the user says "use jina", "r.jina.ai", "fetch
  this blocked page", "tunnel it", "go around the 429", "wayback this", "is
  there a snapshot", or asks to read a site that 403s curl or WebFetch. Not
  for ordinary open-web lookups: WebSearch and WebFetch come first, and this
  skill starts only at a real wall signal.
metadata:
  version: 1.0.0
---

# Jina Lord: The Blocked-Fetch Retrieval Ladder

A five-rung escalation ladder from the open web to a real browser, plus the
diagnosis discipline that decides when to climb. Every rung, header, parse
rule, and gotcha below was field-proven on a large newspaper-archive research project (loc.gov Chronicling
America, hmdb, archive.org, the Veridian newspaper archives) between
2026-07-13 and 2026-08-16, re-verified live on 2026-09-24 while this file was
written, then adversarially re-tested the same day (every bash block below was
run under bash 3.2 and zsh 5.9; the numbers quoted are from those runs). It
supersedes the public `fetching-blocked-urls` 0.1.1 (kept at `SKILL.md.orig`),
which was a single-rung jina wrapper.

The one-line law: **an empty result is a diagnosis, not a throttle. Change one
variable, run one call, read the STATUS line.**

## When to reach for it, and when not to

**Rung 0 law: plain search needs no proxy. The reader is for walled sites, and only when a normal fetch is not enough.** Open-web lookups (encyclopedias, Ballotpedia,
historical societies, .gov pages, marker databases, Wikipedia, API endpoints)
go WebSearch to find, WebFetch to read, plain curl for grep-style checks. jina
spends metered key quota and adds tens of seconds of latency plus its own
failure modes (Turnstile interception, truncated shells); routing an ordinary
lookup through it is the wrong rung.

Start climbing only on a wall signal:

| Signal | What it usually is | First rung |
|---|---|---|
| 403 with default curl, 200 with a browser User-Agent (findagrave, verified 2026-09-24) | UA-only block | 1 |
| 403 with and without a browser UA (hmdb; loc.gov collections JSON after a burst) | Cloudflare / fingerprint | 2 |
| Body says "Just a moment", "Verify you are human", "Checking your browser"; `cf-mitigated` header; `challenges.cloudflare.com` iframe; `<div class="cf-turnstile">`; a ~300-char interstitial | Turnstile / managed challenge | 2, then 5 |
| 418 with an obfuscated-JS body (UDN `newspapers.lib.utah.edu` search and details routes, verified 2026-09-24) | Bot wall by status code, aimed at non-browser clients | 2 (the keyed reader passed both routes the same day), or the site's own API (`api.lib.utah.edu`) |
| 200 but `Title: Error \| <site>`, "Access Denied", a login form, or a body far shorter than the page should be (britannica through the reader, verified 2026-09-24) | Soft block served as a page | 5 |
| 200 from the reader whose body is `Title: Just a moment...` plus `Warning: This page maybe requiring CAPTCHA` (the Veridian archives, verified 2026-09-24) | The proxy itself was challenged | One backoff retry, then 5 |
| Empty body, or an SPA shell with no article text | JS rendering needed | 2 with `X-Engine: browser` |
| 429 from `archive.org/wayback/available` | Per-IP limit on the availability API | 4 (the go-around) |
| 402 from `r.jina.ai` | Key balance exhausted | `health`, then flag the top-up |

**The selenium scope clause: the stealth browser is only for pages that need it. A plain search or an unwalled page through it is slower and less effective.** Rung 5 is reserved for genuine
Turnstile / PerimeterX / managed-challenge grounds (the Veridian archives:
digmichnews, nyshistoricnewspapers, virginiachronicle, CHNC, WY;
NewspaperArchive; amlegal). Never route a plain open-web search or an unwalled
page through it; if WebSearch is exhausted, use rung 3 or plain curl.

## Key handling

Lookup order, first hit wins: `JINA_API_KEY` in the environment, else
`~/.config/jina/api_key`.
All three hold the bare 65-character `jina_...` token with no `KEY=` prefix.
Never print the key; confirm presence by length only.

```bash
if [ -z "$JINA_API_KEY" ]; then
  for f in "$HOME/.config/jina/api_key" "${JINA_API_KEY_FILE:-}"; do
    [ -s "$f" ] && { JINA_API_KEY="$(tr -d '[:space:]' < "$f")"; export JINA_API_KEY; break; }
  done
fi
echo "key length: ${#JINA_API_KEY}"   # expect 65; never echo the value
```

Shell facts that cost real sessions:

- The Claude Code Bash tool is a non-interactive login zsh (`[[ -o
  interactive ]]` false, `[[ -o login ]]` true, verified 2026-09-24), so it
  never reads `~/.zshrc`; it reads `~/.zshenv` (every zsh) and `~/.zprofile`
  (login zsh). The export lives in `~/.zshenv`, which is why the key is in
  the tool shell (length 65, verified). `~/.bashrc` carries the same line for
  interactive bash terminals; a `bash script.sh` started from the tool shell
  inherits the export from its zsh parent, while a bare `env -i bash -c`
  does not (non-interactive bash reads no rc file at all).
- Every Bash tool call is a fresh shell. An `export` in a previous call is
  gone. If the key is missing, prefix the load in the SAME command:
  `export JINA_API_KEY="$(tr -d '[:space:]' < ~/.config/jina/api_key)" && python3 ...`
- Balance check (the `health` subcommand does this):

```bash
curl -s --max-time 30 -H "Authorization: Bearer $JINA_API_KEY" \
  "https://embeddings-dashboard-api.jina.ai/api/v1/api_key/user?api_key=$JINA_API_KEY" \
| python3 -c 'import json,sys; print("total_balance tokens:", json.load(sys.stdin)["wallet"]["total_balance"])'
```

657,401,036 tokens on 2026-09-24 (657,060,948 a few hundred calls later the
same day; recharged to ~906M on 2026-07-14 for ~$50). The dashboard balance
updates with a lag of minutes (it read the same before and after a
14,744-token call), so the per-call charge is the `x-usage-tokens` response
header, not the balance. The reader bills output tokens only; `X-Token-Budget`
409s are unbilled; `s.jina.ai` bills a flat
10,000 per call with or without `X-Respond-With: no-content`
(`meta.usage.tokens` is 10000 either way, verified 2026-09-24: 8 hits at
1,250 each, or 3 hits at 3,334 each with content).

## The ladder

Cheapest rung first. Escalate only on a real wall, one rung per step. Read the
STATUS line before deciding.

### Rung 0: WebSearch / WebFetch (the open web)

Native tools. No key, no latency, no proxy stochasticity. If this works, stop;
the rest of this file does not apply.

### Rung 1: plain curl with a real browser User-Agent and Accept headers

Many 403s are UA-only. Default curl sends `curl/8.x`, which some origins
reject outright. Verified 2026-09-24 under bash 3.2 and zsh 5.9:
`findagrave.com/memorial/1/` returns 403 (`Attention Required! | Cloudflare`,
5,486 bytes) with the default UA and 301 then 200 (268-274 KB, `Cleveland Abbe
(1838-1916) - Find a Grave Memorial`) with the headers below. Always `-L`; the
first success is often a redirect.

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
curl -s -L --max-time 40 -A "$UA" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: en-US,en;q=0.9" \
  -o /tmp/p.html -w "http=%{http_code} bytes=%{size_download} final=%{url_effective}\n" \
  "https://www.findagrave.com/memorial/1/"
grep -o "<title>[^<]*</title>" /tmp/p.html | head -1
```

Not a UA-only site if the code stays 403 with these headers (hmdb, britannica,
loc.gov after a burst): go to rung 2 without further UA tinkering. One
variable per retry means the UA gets one try, not five.

For loc.gov the JSON and microservice endpoints are rung 1 and need no key:
`www.loc.gov/...?fo=json` (search and resource JSON, 20/min with a 1-hour
block on violation, so pace at one call per 3-4 s and cap `c=40`),
`tile.loc.gov/text-services/...` and `tile.loc.gov/image-services/iiif/...`
(150/min, never Turnstile-walled), `tile.loc.gov/storage-services/<segment>.xml`
(raw ALTO, no key). Only the HTML viewer and the collections search after a
burst throw the Turnstile.

### Rung 2: r.jina.ai keyed reader (the tunnel)

`r.jina.ai/<url>` fetches the URL from jina's own infrastructure with a real
browser and returns the page as text. It passes the loc.gov
Cloudflare/Turnstile wall that 403s plain curl (and blocks GPT-Pro's browser),
passes hmdb (verified 2026-09-24: browser-UA curl gets a 403 `Just a moment`,
the reader a 200 of 102,863 bytes, the real FAQ page), passes UDN's 418 wall
(verified 2026-09-24 on `/search?q=` and a `/details?id=` page: 418 to curl,
200 with the page title through the reader), tunnels robot-checked
encyclopedias (mississippiencyclopedia.org, verified 2026-09-24:
`/entries/monroe-county/` is a 75 KB `403 - Forbidden` page to browser-UA
curl and `Title: Monroe County | Mississippi Encyclopedia` through the
reader), and reaches archive.org from a different IP pool (rung 4).

The exact header set, on the FIRST attempt. The 2026-07-19 fix: the old code
used the browser engine only on retry, so the first attempt hit the walled
direct rung plus a non-browser proxy error, and a paid, healthy key looked
"throttled".

```bash
U="https://www.loc.gov/collections/chronicling-america/?q=%22brass+band%22&fa=location_state%3Aarkansas&fo=json&at=results,pagination&c=40"
curl -s --max-time 90 \
  -H "Authorization: Bearer $JINA_API_KEY" \
  -H "X-Engine: browser" \
  -H "X-No-Cache: true" \
  -H "X-Token-Budget: 120000" \
  -o /tmp/r.txt -w "http=%{http_code} bytes=%{size_download} t=%{time_total}s\n" \
  "https://r.jina.ai/$U"
head -c 300 /tmp/r.txt
```

What each header buys (each one re-tested live 2026-09-24; the evidence is
the number in parentheses):

- `Authorization: Bearer <key>`: the keyed tier. It lifts the reader's rate
  limit from 20 requests/min to 500/min (`x-ratelimit-limit: 20, 20;w=60`
  anonymous vs `500, 500;w=60` keyed) and is what the balance is billed
  against. Anonymous calls still answer on most pages (a Wikipedia page came
  back fresh, no `Warning:` lines; httpbin was refused with a 403). The
  `Warning: This is a cached snapshot...` line is a cache tell, not a tier
  tell: it appeared on a keyed call that hit the cache.
- `X-Engine: browser`: a real rendered browser at the proxy. Honored, as the
  latency shows (44.8 s vs 0.4 s for the same loc.gov JSON, byte-identical
  172,093-byte payload and the same `x-usage-tokens: 54166`; 6.5 s vs 0.65 s
  on hmdb). With no wall up that day every engine returned the same bytes, so
  its value does not show on a quiet day; it shows on walls and JS shells.
  hunt_ca2.py's 2026-07-19 fix moved it to the FIRST attempt because the
  default engine's first attempt was hitting the loc.gov Turnstile and the
  browser engine passed. Keep it on from the first attempt; the cost is
  seconds, not tokens.
- `X-No-Cache: true`: bypass the reader's cache so a stale page or a stale
  challenge is not replayed. Without it the second call for a Wikipedia page
  answered in 0.3-0.5 s from cache and, with a selector, carried `Warning:
  This is a cached snapshot of the original page` and a two-week-old
  `Published Time`; with it the same page took 2-3 s (a live fetch). Dynamic
  endpoints (httpbin, postman-echo) were never cached either way.
- `X-Token-Budget: 120000`: an unbilled circuit breaker. loc.gov bakes a
  ~1.76 MB `datasets` field into collections JSON; one unfiltered search once
  billed ~789K tokens for 13 KB of useful payload. The budget makes a
  mis-filtered URL fail fast with a 409 instead of eating the wallet (budget
  3000 on a 7,899-token page: 409 `BudgetExceededError: Token budget (3000)
  exceeded, intended charge amount 7899`).
- `X-Return-Format: markdown|text|html` (default markdown; `ladder.py fetch
  --format` sets it): `text` returns the page as plain text WITHOUT the
  `Title:` / `URL Source:` / `Markdown Content:` header block (12,325 bytes
  for the Wikipedia page vs 27,065 as markdown), `html` returns the raw HTML
  (174,371 bytes). The unwrap rule below applies to markdown only. Does
  nothing on `fo=json` URLs.

Retry policy: up to 4 attempts, backoff `4 + 3*i` seconds (4, 7, 10, 13).
Seconds, not minutes. A minimal loop that runs in both zsh and bash (verified
2026-09-24 under both; it defines `U` itself because every Bash tool call is a
fresh shell):

```bash
U="https://www.loc.gov/collections/chronicling-america/?q=%22brass+band%22&fa=location_state%3Aarkansas&fo=json&at=results,pagination&c=40"
for i in 0 1 2 3; do
  code=$(curl -s --max-time 90 \
    -H "Authorization: Bearer $JINA_API_KEY" -H "X-Engine: browser" \
    -H "X-No-Cache: true" -H "X-Token-Budget: 120000" \
    -o /tmp/r.txt -w "%{http_code}" "https://r.jina.ai/$U")
  if grep -q BudgetExceededError /tmp/r.txt; then echo "STATUS: BUDGET"; break; fi
  if [ "$code" = "402" ]; then echo "STATUS: KEY-402"; break; fi
  if head -c 200 /tmp/r.txt | grep -q '"data":null'; then echo "transient proxy error, retry $((i+1))"; sleep $((4+3*i)); continue; fi
  if grep -q "Just a moment" /tmp/r.txt; then echo "STATUS: CHALLENGE (via proxy, stochastic)"; sleep $((4+3*i)); continue; fi
  echo "STATUS: ok http=$code bytes=$(wc -c < /tmp/r.txt | tr -d ' ')"; break
done
```

Unwrap and parse (the rules that made the keyed rung usable):

```bash
# text body only: everything after the "Markdown Content:" line
sed -n '/^Markdown Content:/,$p' /tmp/r.txt | sed '1d' > /tmp/body.md

# JSON endpoints through the reader: unwrap, scrub control chars, then parse
python3 - <<'PY'
import re, json
raw = open('/tmp/r.txt', encoding='utf-8', errors='replace').read()
if 'Markdown Content:' in raw:
    raw = raw.split('Markdown Content:', 1)[1]
raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', raw)   # loc.gov bakes control chars into its JSON
d = json.loads(raw[raw.index('{'):])
print('total:', d.get('pagination', {}).get('of'), '| shown:', len(d.get('results', [])))
PY
```

Shrinking a request when the budget trips (never raise the budget):

- JSON endpoints: field-filter at the source. loc.gov honors
  `&at=results,pagination` (1.9 MB to 22 KB, ~99% cut, verified 2026-07-14)
  and `c=40` is the payload ceiling (`c=250` truncates mid-body).
  `X-Target-Selector` and `X-Return-Format` do nothing on `fo=json` URLs.
- HTML pages: `X-Target-Selector: <css>` returns only that region. Verified
  2026-09-24 on the Wikipedia Chronicling America page: budget 3000 alone
  gives a 409 (intended charge 7,899); budget 3000 plus
  `X-Target-Selector: #firstHeading` gives a 200 of a few hundred bytes
  holding only the heading (283 bytes raw, 169 through `ladder.py fetch
  --selector`). A selector that
  matches nothing returns a 422 `AssertionFailureError: No content available
  for URL ... with target selector ...`; that is a fix-the-selector, not a
  retry.

### Rung 3: s.jina.ai open-web search

A plain HTTP POST, not a search tool call, so it carries no WebSearch tool
signature. Under `X-Respond-With: no-content` it returns URLs, titles, and
descriptions with `content` empty; the call bills a flat 10,000 tokens with
or without that header, so the header buys speed and payload (1.2 s and 3 KB
vs 17.5 s and 34 KB for the same query with content, verified 2026-09-24),
not tokens. On Seal it is the 0-check and identity-check surface; in general
it is the fallback search when WebSearch is exhausted or unavailable.

```bash
curl -s --max-time 60 -X POST "https://s.jina.ai/" \
  -H "Authorization: Bearer $JINA_API_KEY" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -H "X-Respond-With: no-content" \
  -d '{"q":"\"W. H. Kidd\" Aberdeen Mississippi","num":8}' \
| python3 -c 'import json,sys; d=json.load(sys.stdin); [print(h["title"][:82], "\n ", h["url"]) for h in d.get("data") or []]'
```

Response shape (verified 2026-09-24): top-level `code`, `status`, `data`,
`meta`; each hit in `data[]` has `title`, `url`, `description`, `content`
(empty under no-content), `usage`; `meta.usage.tokens` is 10000. No hits or
an error: print the first 200 bytes of the raw body and read them; do not
theorize.

### Rung 4: the archive.org go-around and the content law

`archive.org/wayback/available` rate-limits per IP; CDX
(`web.archive.org/cdx/search/cdx`) 503s under load. `web.archive.org/web/<ts>/<url>`
captures are usually not limited even while the availability API is.

The worked example is the UMFRIED case: the modern loc.gov resource page of
the Wadsworth Dispatch 1903-02-27, whose 2025-02-16 capture embeds the full
OCR. Both shells, 2026-09-24: availability `closest` 20250216103057 on both
channels, CDX 200, a 1,416,219-byte capture, `umfried 3`, `beemer 24`.

```bash
P='www.loc.gov/resource/sn86076138/1903-02-27/ed-1/'

# 4a. availability, direct (http first; https is the one-variable retry)
curl -s --max-time 40 "http://archive.org/wayback/available?url=$P"; echo

# 4b. the go-around: the SAME URL through the reader = a different IP pool
#     (EXAMPLE_LOG #19: worked first try after a full night of direct 429s);
#     the JSON arrives after "Markdown Content:", unwrap as in rung 2
curl -s --max-time 60 -H "Authorization: Bearer $JINA_API_KEY" -H "X-Token-Budget: 60000" \
  "https://r.jina.ai/https://archive.org/wayback/available?url=$P" | sed -n '/^Markdown Content:/,$p' | sed '1d'

# 4c. CDX, wildcard; if one scheme 503s, vary ONE variable: the other scheme
ENC=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$P")
curl -s --max-time 40 -o /tmp/cdx.json -w "cdx http=%{http_code} bytes=%{size_download}\n" \
  "https://web.archive.org/cdx/search/cdx?url=${ENC}*&output=json&limit=40"
TS=$(python3 -c 'import json; r=[x for x in json.load(open("/tmp/cdx.json"))[1:] if x[4]=="200"]; print(r[0][1] if r else "")')
echo "first 200 capture: ${TS:-none}"

# 4d. THE CONTENT LAW: pull the raw capture (id_ = no toolbar), normalize <br/>,
#     strip tags, grep the tokens. Truncate the file first and gate on the code:
#     a failed pull leaves the previous run's bytes behind, and a 404 here is
#     "no capture at that timestamp", never a clear.
rm -f /tmp/cap.bin
CODE=$(curl -s -L --max-time 120 -o /tmp/cap.bin -w "%{http_code}" "https://web.archive.org/web/${TS}id_/$P")
echo "capture http=$CODE bytes=$(wc -c < /tmp/cap.bin | tr -d ' ')"
[ "$CODE" = "200" ] && python3 - <<'PY'
import re, subprocess
raw = open('/tmp/cap.bin', 'rb').read()
if raw[:5] == b'%PDF':   # the WRIGHT lesson: a PDF's compressed text layer greps 0 in raw bytes
    txt = subprocess.run(['pdftotext', '/tmp/cap.bin', '-'], capture_output=True).stdout.decode('utf-8', 'replace')
else:
    t = raw.decode('utf-8', 'replace')
    t = re.sub(r'<br\s*/?>', ' ', t, flags=re.I)
    txt = re.sub(r'<[^>]+>', ' ', t)
low = txt.lower()
for tok in ['umfried', 'beemer']:
    print(tok, low.count(tok))
PY
```

A snapshot's existence is never the verdict; its content is. A ~5 KB
issue-level capture is index-only; a METS XML capture is metadata-only (the
LABOYE case: gate clear, not margin); a 47 KB 2024 seq capture embedded the
full OCR (the LOWREY case: kill-grade); the 1.4 MB 2025 capture of the modern
resource page above renders the answer tokens (the UMFRIED case). The modern
resource URL without `?sp=` is a distinct URL from `?sp=1`: gate both forms
explicitly (the `lccn:` spec form expands to `?sp=N`, which does not
prefix-match the no-`?sp` capture that killed UMFRIED). No date-based clears:
every capture, any date, gets the pull-and-grep. A CDX error must never fall through to a
"no captures" verdict; the gate is INCOMPLETE until the erred channel is
re-run.

Live evidence for the blocked-claim rule (2026-09-24, while ladder.py was
written): CDX over http returned a 503 whose body literally says `Internet
Archive: Temporarily Offline`; https timed out; the reader route returned a
422 with a `TimeoutError` cause. That is the one shape where "the service is
down" may be said out loud, because the response says so. The same afternoon
both schemes answered `[]` in 3 bytes, and minutes later four of eleven
capture pulls over http failed with `Failed to connect to web.archive.org port
80` while the https pulls succeeded. On 2026-07-27: four http 503s, then `[]`
first try on https. Vary the scheme before concluding anything.

### Rung 5: the real-browser tier (seleniumbase-stealth)

Hand off, do not reimplement. The `seleniumbase-stealth` plugin
(`stealth-browsing` skill, `/stealth-fetch` command) owns Turnstile /
PerimeterX / managed-challenge grounds with a real Chrome fingerprint, UC
Mode, and CDP Mode:

| Tool | Use |
|---|---|
| `stealth_fetch(url)` | one-off read; opens Chrome, clears the challenge, returns markdown, closes |
| `stealth_fetch(url, reconnect=8, settle=4)` | slow site or heavy challenge |
| `cdp_fetch(url)` | CDP Mode, no WebDriver, when `stealth_fetch` is still challenged |
| `session_open` / `session_read` / `session_execute_js` / `session_close` | multi-step work; land once, then in-session same-origin `fetch()` for content (the Veridian `getSectionText` route); always close |

Go there when: rung 2 returned CHALLENGE twice with backoff (the Veridian
shape through the reader is `Title: Just a moment...` plus `Warning: This page
maybe requiring CAPTCHA`, 499 bytes, verified 2026-09-24 on digmichnews), or
the site is a known stealth-tier ground (the Veridian archives,
NewspaperArchive, amlegal, britannica: through the reader britannica is
either a 747-byte proxy-caught challenge or a 200 `Error | Britannica` soft
block, both seen the same day), or the 403 survives both a browser UA and the
keyed reader. UDN is not on that list: its 418 is a curl wall the reader
passes. Do not go there for anything rungs 0-4 can read. The CAPTCHA click is
that plugin's explicit flow (`session_solve_captcha`, driven by
`uc_gui_click_captcha`: a real cursor moves; macOS Accessibility permission
is required); this skill never solves a CAPTCHA programmatically.
For batch hunts, the driver-script form
(`~/.seleniumbase-stealth/venv/bin/python /tmp/<name>.py`, one profile per
site, land once, AJAX for content, filtered windows out) beats per-call MCP
by 2-3x.

## The script: ladder.py

`scripts/ladder.py` (this plugin) wraps the rungs with the STATUS line built
in. It descends from the author's earlier `hunt_ca2.py` (`fetch()`
ladder, `as_json()`, `search_web()`) and `wayback_gate.py`. Run with the key
loaded (or `JINA_API_KEY_FILE=<path>` to name one key file;
`JINA_API_KEY_FILE=/dev/null` runs keyless on purpose); the key never appears
on argv, in a trace, or on stdout. The plugin root resolves as
`${CLAUDE_PLUGIN_ROOT}` inside the plugin, or
`/path/to/web-retrieval-ladder` in development.

```bash
L="${CLAUDE_PLUGIN_ROOT:-/path/to/web-retrieval-ladder}/scripts/ladder.py"
python3 "$L" fetch "https://www.hmdb.org/m.asp?m=1"                  # rung 1 -> rung 2; STATUS line, then the unwrapped body
python3 "$L" fetch "https://en.wikipedia.org/wiki/Chronicling_America" --selector "#firstHeading"   # X-Target-Selector (starts at rung 2)
python3 "$L" search '"W. H. Kidd" Aberdeen Mississippi' 8             # rung 3: URLs + titles
python3 "$L" wayback "www.loc.gov/resource/sn86076138/1903-02-27/ed-1/" --grep umfried,beemer   # rung 4: availability (go-around on 429), CDX, pull-and-grep
python3 "$L" health                                                   # key source (never the key), balance, a reader probe
python3 "$L" diagnose "https://www.britannica.com/place/Venice-California"   # both fetch rungs once, each with its first 200 bytes
python3 "$L" fetch "https://example.com" --rung 5                     # prints the exact stealth handoff and exits 2; never drives a browser
```

`fetch` flags: `--rung 1|2|5` (start rung; 5 only prints the handoff),
`--selector <css>` (X-Target-Selector; implies rung 2), `--format
markdown|text|html` (X-Return-Format at rung 2; tag-stripped text or the raw
body at rung 1), `--max-chars N`, `--out FILE` (content to the file, STATUS
still on stdout; falls back to stdout if the file cannot be written),
`--timeout S`.

The output contract (the script's docstring is the full text): EVERY
subcommand prints, as its FIRST stdout line,

    # STATUS: <verdict> | rung=N | <diagnosis; next move>

then its content (`fetch`: the body; `search`: the hits; `wayback`: the
per-URL report and a `VERDICT:` line; `health`: key source, balance, probe;
`diagnose`: the rung table). Per-try trace lines (`# rung=2 try 1/4: ...`,
`# rung=2 backoff 4s ...`) go to stderr. Rung numbers in the STATUS line
match this file: `fetch` reports 1, 2, or 5; `search` reports 3; `wayback`
reports 4 (`ok` for `FULL MARGIN` and `CAPTURES EXIST`, `EMPTY-RAW` for
`GATE INCOMPLETE`); `health` reports 2. Exit codes: 0 ok, 2 channel problem
(retry once, do not loop), 3 usage; an internal error is a `PARSE-FAIL`
STATUS with `rung=-`, exit 2, traceback on stderr. Lines seen 2026-09-24:

    # STATUS: ok | rung=2 | rung 1 CHALLENGE (http 403, signature "Just a moment"); jina browser engine passed; proxy http 200, 106715b in 9.0s
    # STATUS: ok | rung=3 | 3 hit(s) for: "W. H. Kidd" Aberdeen Mississippi
    # STATUS: ok | rung=4 | VERDICT: CAPTURES EXIST -- adjudicate per the content law; 7 target capture(s) render the tokens (KILL-GRADE); 4 sibling row(s) listed, not pulled
    # STATUS: ok | rung=2 | key accepted, balance 657060948
    # STATUS: CHALLENGE | rung=5 | this script does not drive a browser; run stealth_fetch(url="https://example.com")  [seleniumbase-stealth MCP; cdp_fetch if still challenged; or the /stealth skill]

`diagnose` on britannica is the "a 200 is not a verdict" case on one screen:
rung 1 is a 403 `Just a moment`; rung 2 is either a proxy-caught challenge or
an `ok` whose first 200 bytes begin `Title: Error | Britannica`. Read the
bytes, not the verdict.

## STATUS-line triage

Every failure prints one STATUS line naming the cause. Read it; do not
theorize past it.

| STATUS | Meaning | Do next |
|---|---|---|
| `ok` | Bytes landed and parsed | A 200 is not a verdict. Check `Title:` and the body: `Error \| <site>`, "Access Denied", a login form, or a body far shorter than the page should be is a soft block (rung 5); a `Warning: This is a cached snapshot` line means the cache answered (add `X-No-Cache: true`); `Title: Just a moment...` with `Warning: This page maybe requiring CAPTCHA` is a CHALLENGE the proxy caught, not content. |
| `EMPTY-RAW` | Every rung returned nothing or a shell; also a bare 4xx with no challenge signature at rung 1 (`http 403, no challenge signature`), a proxy error a retry cannot change (DNS, a refused private target, a selector that matched nothing), or `wayback`'s `GATE INCOMPLETE` | An instrument problem, never a corpus zero. Read the clause first: `target-error` and DNS mean fix the URL, not the channel; a selector miss means fix the selector. Otherwise change ONE variable and run ONE call: `+` for spaces instead of `%20` (loc.gov challenges `%20` queries), a smaller payload (`c=40`, `&at=`), the encoded form of a two-word facet value, the next rung. |
| `CHALLENGE` | "Just a moment", "Verify you are human", `cf-turnstile`, or a ~300-char interstitial | Direct rung: go to rung 2. Rung 2: the proxy is stochastic and can itself catch a Turnstile; one challenge via jina is not a verdict, retry once with backoff, then rung 5. If the calls were bursted, the wall is self-thrown: 30-60 s, then single calls only. |
| `PARSE-FAIL` | Bytes arrived but did not parse, or the transfer truncated; from `ladder.py` with `rung=-` it is an internal error (traceback on stderr) | Suspect the parse, not the key or a cooldown. Unwrap after `Markdown Content:` (markdown format only; `text` and `html` have no wrapper), scrub control chars, retry ONCE with a smaller count. About 1 in 6 tile pulls arrives truncated; one retry fixes it. |
| `BUDGET` | 409 `BudgetExceededError` (unbilled) | Shrink the request: `&at=results,pagination` on JSON, `X-Target-Selector` on HTML. Never raise the budget. |
| `KEY-402` | 402 Payment Required, or 401 (key missing or rejected) | 402: the balance is exhausted; run `health`, flag the top-up. 401: the key was not sent or is wrong; check the length (65) and the lookup order. Anonymous `r.jina.ai` still answers for a one-off, at 20 requests/min instead of 500. |
| `RATE-429` | The origin rate-limited this IP | archive.org availability: the same URL through `r.jina.ai`. loc.gov JSON: 20/min with a 1-hour block; count calls, pace 3-4 s, never burst. Wikipedia API bursts draw 429 too: a driver script, not a faster loop. Back off seconds, not minutes. |
| `TIMEOUT` | `--max-time` expired, or the proxy returned 422 `AssertionFailureError` with a `TimeoutError` cause | Transient. Retry with the `4 + 3*i` backoff. If the origin body literally says it is offline, that is the evidence for a down claim; record the rung as owed with the ladder listed. |

## Diagnosis discipline

1. **An empty result is a diagnosis, not a throttle.** Empty means a bad or
   wrapped phrase, a date filter dropping everything, an unmapped facet value,
   a `%20` where a `+` was needed, or a self-thrown Turnstile from bursting.
   It does not mean the key is rate-limited. The lesson, learned the expensive way: nothing had cooled; it was the methodology, not the website.
2. **Change exactly one variable per retry.** The variables: User-Agent, URL
   encoding, the rung, pacing, scheme (http vs https), exact vs wildcard form,
   payload size. Two changes at once teach nothing.
3. **One call at a time.** Do not burst. Bursting the loc.gov collections
   endpoint self-inflicts a Cloudflare challenge that then blocks even the
   keyed reader; `tile.loc.gov` reads keep working the whole time, so the
   wall is on the search endpoint that was hammered, not the site.
4. **Read the STATUS line, then the raw bytes.** `head -c 300` of the body
   before any theory. The 2026-07-19 "throttle" was three parse bugs and a
   healthy key.
5. **Never narrate cooldowns.** No "cooling jina 55 s", no "the shared key is
   hot", no `sleep 45/55/70`. Back off `4 + 3*i` seconds inside the retry
   loop and say nothing about it.
6. **"Blocked" may be claimed only when the response literally says so.** A
   4xx/5xx is a debugging lead. The variation ladder (scheme, encoding, exact
   vs wildcard, pacing, route) is cheap; a rung is recorded as owed only after
   the ladder is exhausted, with the ladder listed.
7. **A 200 is not a verdict.** Check the title and body. britannica through
   the reader is a 200 whose title is `Error | Britannica`.
8. **Never solve a CAPTCHA here.** That is the stealth tier's explicit,
   warned, cursor-moving flow.
9. **Back up every claim used to stop or defer work** with the observed
   evidence in the same breath (the exit code, the STATUS line, the first
   bytes). Unverified limit claims read as laziness.

## Parse gotchas

- **The reader wrapper.** Output is `Title:`, `URL Source:`, optionally
  `Published Time:` and `Warning:` lines, then `Markdown Content:` and the
  body. JSON endpoints arrive as JSON after that marker; strict `json.loads`
  on the whole body fails.
- **Control characters.** loc.gov bakes `[\x00-\x08\x0b\x0c\x0e-\x1f]` into
  its JSON. Scrub before any parse.
- **`"data":null` in the first 200 bytes is a proxy error, never content.**
  Three sub-cases, checked in this order: (a) `BudgetExceededError` (409) also
  carries `"data":null`, so test for it first and treat it as BUDGET, not
  transient; (b) `AssertionFailureError` (422) with a `cause.log` and a
  `TimeoutError` name is transient, retry; (c) 422 `No content available for
  URL ... with target selector` is a selector miss, fix the selector.
- **Italics become underscores mid-string.** The reader renders page italics
  as `_Cotter Courier_`, so an exact-phrase grep across an italicized span
  false-misses while the clause verifies in a browser (the HENLEY case). Grep
  the distinctive non-italic words, or eyeball the rendered page.
- **Cache and challenge tells.** `Warning: This is a cached snapshot of the
  original page, consider retry with caching opt-out` means the cache
  answered (seen on a keyed call, 2026-09-24): add `X-No-Cache: true`.
  `Warning: This page maybe requiring CAPTCHA, please make sure you are
  authorized to access this page` under `Title: Just a moment...` means the
  proxy itself was challenged: CHALLENGE, not content.
- **Line wraps in OCR.** A phrase that wraps across a line ("brass\nband")
  misses in search indexes and in greps; pick a phrase that renders on one
  line.
- **Index thinness, not an instrument gap.** A low or zero total for a real
  phrase is a per-phrase limit of the loc.gov search index (early OCR indexes
  some phrases thinly or line-wrapped), not a curl-vs-browser gap: on
  2026-09-24 direct curl, the default engine, and the browser engine all
  returned total 2891 for the same query. The old "curl 3 vs browser 37"
  reading was corrected on 2026-07-19 (rule 4). Confirm the phrase against the page's ALTO text before concluding.
- **Binary captures.** `%PDF` or a NUL in the first 400 bytes means raw-byte
  greps prove nothing; `pdftotext` first, and an image capture is graded as
  the giant-file channel, not cleared.

## Limits stated plainly

- The reader is slow (tens of seconds per page with the browser engine),
  stateless (every page pays the full toll), metered (a 402 ends it until
  top-up), and it mangles layout details (italics, some tables). It is the
  walled-tier fallback, not a crawler.
- The reader passes loc.gov, hmdb, mississippiencyclopedia.org, UDN (a 418
  to curl, the page through the reader), archive.org. It does not pass the
  Veridian archives (`Title: Just a moment...` plus the CAPTCHA warning) and
  is unreliable on britannica (a proxy-caught challenge or a 200 soft-block
  error page); those are rung 5 grounds.
- The proxy is stochastic. It can catch a Turnstile itself. One challenge via
  jina proves nothing about the site.
- archive.org: the availability API 429s per IP; CDX 503s under load;
  `web.archive.org` captures usually pull fine. In the archive workflow this ladder came from, wayback
  captures, archive.org, and HathiTrust are instrument-only and banned as
  cited sources.
- DataDome and similar behavioral systems are not beatable at any rung here,
  including rung 5; say so rather than retrying.
- Long pages truncate; login-walled content is limited to public portions;
  real-time dynamic content may not render.
- A blind solver that independently derives the `r.jina.ai` trick can
  tunnel-solve a walled page. The tunnel is this session's instrument; it is
  not evidence about what another model can reach.

## Provenance

The author's working notes; scripts `hunt_ca2.py`, `wayback_gate.py`;
`docs/EXAMPLE_LOG.md` sections 8, 19, 21; `docs/DRIVER_SCRIPTS_EVOLUTION.md`;
the `stealth-browsing` skill. Live re-verification 2026-09-24 (twice: the build and an adversarial pass the
same day, every bash block run under bash 3.2 and zsh 5.9): findagrave
UA-only 403; hmdb, mississippiencyclopedia, and UDN through the reader;
britannica soft-block and proxy-caught challenge; the Veridian challenge
shape; UDN 418; the 409 and 422 shapes; `X-Target-Selector`;
`X-Return-Format`; the 20-vs-500 rate-limit headers; the cache `Warning:` on
a keyed call; the balance endpoint; the `s.jina.ai` response shape and flat
charge; the CDX offline body; the UMFRIED capture pull-and-grep.
