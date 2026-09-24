#!/usr/bin/env python3
"""wall_detect.py -- PostToolUse / PostToolUseFailure hook for web-retrieval-ladder.

Reads the hook JSON from stdin, scans the output of a WebFetch or Bash call for
anti-bot wall signatures, and on a hit prints a hookSpecificOutput block whose
additionalContext names the signature and the exact next command. On no hit it
prints nothing. It always exits 0 and swallows every exception: a hook must never
break a tool call. Nothing outside the guarded entry point does work.

Why two events: a Bash command that fails (curl -f on a 403 exits 22) and a
WebFetch that throws are delivered to PostToolUseFailure with an `error` string,
not to PostToolUse with a tool_response. Both shapes are handled here.

Diagnosis discipline (the reason this exists): a wall is a DIAGNOSIS, not a
throttle. The context names the signature, names the next rung (ladder.py
diagnose / fetch), and forbids re-running the identical fetch. It never asks the
model to solve a CAPTCHA.

Precision rules (each one cost a false positive in testing):
  * Only WebFetch and Bash are scanned, whatever the matcher says.
  * A numeric WebFetch code is the verdict: 403/418/429 fire; a 2xx page only
    fires on a STRONG interstitial phrase, never on prose about HTTP errors.
  * STRONG signatures (Cloudflare interstitial text, the Turnstile widget,
    Incapsula, PerimeterX markers) count in the first EARLY_WINDOW chars or in
    a small body. SOFT signatures ("Access Denied", "403 Forbidden", DataDome)
    count only in a small body or inside <title> / <h1> / a reader Title: line,
    so a nav link labelled "Access Denied" in a 40 KB page is prose.
  * WebFetch's own failure wording counts only for WebFetch, never for Bash
    (bundled JS says "Failed to fetch" all the time).
  * Bash commands whose only tools are git / gh / package managers are skipped
    (their 403/429 are auth and registry limits, not web walls), as is output
    that is already a ladder.py STATUS report.

Stdlib only. Runs in about 30 ms; the scan is capped.
"""
import sys

SCAN_CAP = 200_000       # a wall page announces itself early; cap the scan
EARLY_WINDOW = 1500      # STRONG phrases must sit this early in a large body
SMALL_BODY = 4000        # below this, the whole body is the interstitial
SMALL_BYTES = 2500       # a 2xx WebFetch this small is a block page, not the page
HEADLINE_WINDOW = 20_000 # <title>/<h1> are looked for inside this prefix

# Numeric verdicts: an explicit status wherever it sits (curl -i/-v header lines,
# curl -f's error, WebFetch/axios wording, an instrument's "status: 403" line,
# "code": 403 in JSON). One capture group each.
STATUS_SOURCES = (
    r"^\s*(?:<\s*)?HTTP/[0-9.]+\s+(403|418|429)\b",
    r"(?:^|[\s,;|({\"'])(?:http(?:_code)?|status(?:_code)?|code)[\"']?\s*[:=]\s*[\"']?(403|418|429)\b",
    r"Request failed with status code (403|418|429)\b",
    r"The requested URL returned error:\s*(403|418|429)\b",
)
BARE_STATUS_SOURCE = r"^\s*(403|418|429)\s*$"   # curl -w '%{http_code}' alone
WALL_CODES = {403: "HTTP 403", 418: "HTTP 418", 429: "HTTP 429"}

# (pattern, label). STRONG: interstitial markers that no real page carries early.
STRONG_SOURCES = (
    (r"Just a moment", 'Cloudflare "Just a moment" interstitial'),
    (r"Verif(?:y|ying) you are human", 'Cloudflare "Verify you are human"'),
    (r"Checking your browser", 'Cloudflare "Checking your browser"'),
    (r"Enable JavaScript and cookies to continue", "Cloudflare JS-and-cookies challenge"),
    (r"Performing security verification", "Cloudflare security verification"),
    (r"cf-mitigated:\s*challenge", "cf-mitigated: challenge header"),
    (r"cf-turnstile", "cf-turnstile widget"),
    (r"challenges\.cloudflare\.com", "challenges.cloudflare.com script"),
    (r"_Incapsula_", "Imperva Incapsula"),
    (r"_pxhc\b|px-captcha|PerimeterX", "PerimeterX"),
    (r"(?:^|\n)Title:\s*(?:Error \||Access Denied|Forbidden|403|Just a moment|Attention Required)", "reader Title line is a block page"),
)
# SOFT: words that appear in ordinary prose and nav; need a small body or a headline.
SOFT_SOURCES = (
    (r"\b403 Forbidden\b", "HTTP 403 Forbidden"),
    (r"\bHTTP(?: Error)? (?:403|418)\b", "HTTP 403/418"),
    (r"\bAccess Denied\b", "Access Denied"),
    (r"Attention Required", 'Cloudflare "Attention Required"'),
    (r"DataDome", "DataDome"),
    (r"\b418 I'm a teapot\b", "HTTP 418"),
    (r"\b429 Too Many Requests\b|\bHTTP(?: Error)? 429\b|rate limit exceeded", "HTTP 429 rate limit"),
)
# WebFetch's own failure wording; meaningless inside Bash output.
WEBFETCH_FAIL_SOURCE = r"\b(?:Failed to fetch|fetch failed|Unable to fetch|Could not fetch|Error fetching)\b"

HEADLINE_SOURCES = (r"<title[^>]*>(.{0,300}?)</title>", r"<h1[^>]*>(.{0,300}?)</h1>", r"(?:^|\n)Title:[^\n]{0,300}")
URL_SOURCE = r"https?://[^\s'\"<>)\]]+"
READER_PREFIX_SOURCE = r"^https?://r\.jina\.ai/(https?://.+)$"
AVAILABILITY_SOURCE = r"wayback/available\?(?:.*&)?url=([^&\s]+)"
# ladder.py / wall_detect output, however the command spelled the path.
SELF_OUTPUT_SOURCE = r"(?:^|\n)# (?:STATUS:|rung=)"
SUPPRESS_IN_COMMAND = ("ladder.py", "wall_detect")
# Bash: skip when every command segment is one of these and nothing fetch-like runs.
NON_WEB_TOOLS = {"git", "gh", "npm", "npx", "pnpm", "yarn", "pip", "pip3", "uv", "brew", "cargo",
                 "gem", "bundle", "docker", "kubectl", "aws", "gcloud", "az", "go", "mvn", "gradle"}
WEB_TOOLS = {"curl", "wget", "python", "python3", "node", "http", "https", "xh", "aria2c", "bun", "deno"}
SHELL_NOISE = {"cd", "echo", "export", "set", "sudo", "env", "time", "nohup", "true", "printf", "ls", "cat"}
BODY_KEYS = ("stdout", "stderr", "output", "result", "content", "text", "error", "message")
SCANNED_TOOLS = ("WebFetch", "Bash")


def _flatten(value, depth=0):
    """Pull every string out of a tool_response of any shape."""
    if depth > 4 or value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts = []
        for key in BODY_KEYS:
            if key in value:
                parts.extend(_flatten(value[key], depth + 1))
        if not parts:
            for v in value.values():
                parts.extend(_flatten(v, depth + 1))
        return parts
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(_flatten(item, depth + 1))
        return parts
    return []


def _code_of(resp):
    if not isinstance(resp, dict):
        return None
    raw = resp.get("code", resp.get("status", resp.get("statusCode")))
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def _first_tokens(re, command):
    """First word of every segment of a shell command, minus env assignments."""
    tokens = set()
    for seg in re.split(r"\|\||&&|[;|\n]", command):
        words = seg.strip().split()
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in SHELL_NOISE):
            words.pop(0)
        if words:
            tokens.add(words[0].rsplit("/", 1)[-1])
    return tokens


def _skip_command(re, command):
    if any(token in command for token in SUPPRESS_IN_COMMAND):
        return True
    tokens = _first_tokens(re, command)
    if tokens & WEB_TOOLS or re.search(r"https?://", command):
        return False
    return bool(tokens & NON_WEB_TOOLS)


def _headline(re, body):
    parts = []
    for source in HEADLINE_SOURCES:
        for m in re.finditer(source, body[:HEADLINE_WINDOW], re.I | re.S):
            parts.append(m.group(0))
            if len(parts) >= 8:
                break
    return "\n".join(parts)


def _detect(re, body, code, tool, nbytes=None):
    """Return the label of the first wall signature that counts, or None."""
    if code in WALL_CODES:
        return WALL_CODES[code]
    if not body:
        return None
    if re.search(SELF_OUTPUT_SOURCE, body[:600]):
        return None
    # A 2xx with a body far shorter than any real page is the soft-block shape
    # (SKILL.md: "200 but Access Denied / Error | <site>"); let SOFT words count.
    success_code = isinstance(code, int) and 200 <= code < 300 and not (
        isinstance(nbytes, int) and 0 < nbytes < SMALL_BYTES)
    if not success_code:
        m = re.match(BARE_STATUS_SOURCE, body)
        if m:
            return WALL_CODES[int(m.group(1))]
        for source in STATUS_SOURCES:
            m = re.search(source, body, re.M | re.I)
            if m:
                return WALL_CODES[int(m.group(1))]
    small = len(body) < SMALL_BODY
    head = body if small else body[:EARLY_WINDOW]
    for source, label in STRONG_SOURCES:
        if re.search(source, head, re.I):
            return label
    if success_code:
        return None
    headline = _headline(re, body)
    for source, label in SOFT_SOURCES:
        if (small and re.search(source, body, re.I)) or re.search(source, headline, re.I):
            return label
    if tool == "WebFetch" and small and re.search(WEBFETCH_FAIL_SOURCE, body, re.I):
        return "WebFetch fetch failure"
    return None


def _plugin_root(os):
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        return root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clean_url(re, url):
    if not url:
        return None
    m = re.match(READER_PREFIX_SOURCE, url)
    if m:
        url = m.group(1)
    return url.rstrip(".,;:")


def _context(os, re, label, url):
    ladder = f'python3 "{_plugin_root(os)}/scripts/ladder.py"'
    where = f" for {url}" if url else ""
    target = f'"{url}"' if url else "<url>"
    m = re.search(AVAILABILITY_SOURCE, url or "") if label.startswith("HTTP 429") else None
    if m:
        nxt = (f'{ladder} wayback "{m.group(1)}" (archive.org availability 429s per IP;'
               f" wayback routes the same call through the reader)")
    else:
        nxt = f"{ladder} diagnose {target} (then: fetch {target})"
    text = (
        f"Wall signature: {label}{where}. A wall is a diagnosis, not a throttle: do not re-run the"
        f" identical fetch or narrate cooldowns. Follow the fetching-blocked-urls skill. Next: {nxt}."
        f" One variable per retry (UA, encoding, rung, pacing); act on the STATUS line it prints."
        f" seleniumbase-stealth only for a genuine Turnstile/PerimeterX/managed challenge, never a plain lookup."
    )
    if label.startswith("HTTP 429") and not m:
        text += " A 429 is pacing: single calls, back off seconds, no burst."
    return text


def main():
    import json
    import os
    import re

    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return
    data = json.loads(raw)
    if not isinstance(data, dict):
        return
    tool = str(data.get("tool_name") or "")
    if tool not in SCANNED_TOOLS:
        return
    if data.get("is_interrupt") or data.get("is_timeout"):
        return
    event = str(data.get("hook_event_name") or "PostToolUse")
    if event not in ("PostToolUse", "PostToolUseFailure"):
        event = "PostToolUse"
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    resp = data.get("tool_response")
    parts = _flatten(resp)
    err = data.get("error")
    if isinstance(err, str):
        # A failed Bash call arrives as "Error: Exit code N\n<output>"; drop the prefix
        # so a bare status line or a header line is still the first thing scanned.
        parts.append(re.sub(r"^\s*(?:Error:\s*)?Exit code \d+\s*\n?", "", err))
    body = "\n".join(parts)[:SCAN_CAP]
    code = _code_of(resp)
    url = resp.get("url") if isinstance(resp, dict) and isinstance(resp.get("url"), str) else None

    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if _skip_command(re, command):
            return
        m = re.search(URL_SOURCE, command)
        if m:
            url = m.group(0)
    elif isinstance(tool_input.get("url"), str):
        url = tool_input["url"]

    nbytes = resp.get("bytes") if isinstance(resp, dict) else None
    label = _detect(re, body, code, tool, nbytes)
    if not label:
        return
    out = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": _context(os, re, label, _clean_url(re, url)),
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
