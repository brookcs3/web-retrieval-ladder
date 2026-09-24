#!/usr/bin/env python3
"""ladder.py: the web-retrieval ladder as one stdlib script (plugin web-retrieval-ladder).

Cheapest rung first; escalate only on a real wall. Rung 0 (WebFetch / WebSearch for the
open web) lives in the skill, not here: this script starts where the open web ends.

USAGE
  python3 ladder.py fetch <url> [--rung N] [--out FILE] [--max-chars N] [--selector CSS]
                                [--format markdown|text|html] [--timeout S]
  python3 ladder.py search "<query>" [num]
  python3 ladder.py wayback <url> [<url> ...] [--grep tok1,tok2]
  python3 ladder.py health
  python3 ladder.py diagnose <url>

FETCH RUNGS
  1  plain GET with a real browser User-Agent and Accept headers (many 403s are UA-only).
  2  r.jina.ai reader, keyed: X-Engine: browser on the FIRST attempt, X-No-Cache: true,
     X-Token-Budget: 120000 (an unbilled circuit breaker). 4 tries, backoff 4+3*i seconds.
     Content is unwrapped after "Markdown Content:"; control chars are scrubbed before any
     JSON parse; a body with "data":null in its first 200 chars is a transient proxy error
     (retried, never returned); BudgetExceededError means shrink the request (--selector),
     never raise the budget; a 402 means the key balance is exhausted (run health); the
     proxy is stochastic and can itself catch a Turnstile, so one challenge via jina is not
     a verdict (every try is printed to stderr).
  5  the real-browser tier: seleniumbase-stealth (stealth_fetch / cdp_fetch / session_*),
     ONLY for genuine Turnstile / PerimeterX / managed-challenge walls. This script never
     drives a browser and never solves a CAPTCHA; it prints the exact stealth command.
     (Rungs 3 and 4 are search and wayback below; the numbering matches the skill.)
  --rung N starts the ladder at rung N (1, 2, or 5). --selector applies at rung 2 only
  (X-Target-Selector), so giving one starts the ladder at rung 2; a selector that matches
  nothing is a 422 from the proxy and is reported once, never retried (fix the selector).
  --format at rung 1 gives tag-stripped text for markdown|text (stdlib has no markdown
  converter) and the raw body for html; at rung 2 it is passed as X-Return-Format.

OUTPUT CONTRACT
  EVERY subcommand prints this as its FIRST stdout line:
      # STATUS: <verdict> | rung=N | <diagnosis; next move>
  fetch follows it with the content (stdout, or the --out file with STATUS still on stdout;
  if the --out path cannot be written the content falls back to stdout and the STATUS line
  says so), or nothing on failure. search follows it with the hits, wayback with the
  per-URL report, health with the key/balance/probe lines, diagnose with the rung table
  (each rung's first 200 bytes included). Per-try trace lines go to stderr so a retry is
  visible without polluting the content. Verdict vocabulary, exact:
      ok | EMPTY-RAW | CHALLENGE | PARSE-FAIL | BUDGET | KEY-402 | RATE-429 | TIMEOUT
  Exit codes: 0 ok, 2 channel problem (retry once, do not loop), 3 usage. An internal
  error is reported as a STATUS line (PARSE-FAIL, rung=-) with exit 2, traceback on stderr.

WAYBACK
  availability API (direct http, then https, then the SAME URL through r.jina.ai when
  archive.org 429s or answers empty: a different IP pool), wildcard CDX, and with --grep
  every 200 capture of the TARGET PAGE pulled (web.archive.org; a failed pull is retried
  once over https 8 s later) and grepped: <br/> normalized to spaces, tags stripped, %PDF
  captures through pdftotext. Rows the wildcard over-matches (seq-10/ for seq-1/, ?sp=2
  for ?sp=1) are listed as SIBLING and not pulled (the EZELL-precedent pass). A snapshot's
  existence is never the verdict, its content is. Verdicts exactly as wayback_gate.py:
  FULL MARGIN / CAPTURES EXIST / GATE INCOMPLETE (a channel error never falls through to
  clear); the STATUS line carries the verdict, rung=4. At least 1.5 s between archive.org
  calls. A spec lccn:<lccn>:<date>:<sp> expands to both loc.gov URL forms.

KEY
  JINA_API_KEY from the environment, else ~/.config/jina/api_key, else
  JINA_API_KEY_FILE=<path>, when set,
  replaces that keyfile list with the one path (JINA_API_KEY_FILE=/dev/null runs keyless
  on purpose). The key is never printed: not on stdout, not in a trace, not on curl's
  argv (headers and the dashboard URL travel in a 0600 config file, so ps never sees it).
  The Claude Code Bash tool shell does not source ~/.zshrc; the export lives in ~/.zshenv
  and ~/.bashrc.

DISCIPLINE
  An empty result is a diagnosis, not a throttle. Change exactly ONE variable per retry
  (UA, encoding, rung, pacing). Every failure names its cause. Back off seconds, not
  minutes; no cooldown narration. "Blocked" is claimed only when the response literally
  says so. The jina reader renders italics as underscores mid-string, so exact-phrase
  greps across italic spans false-miss: grep non-italic words.

PROVENANCE
  the author's earlier hunt_ca2.py (fetch, as_json, search_web),
  the author's earlier wayback_gate.py (availability, cdx, grep_capture),
  docs/EXAMPLE_LOG.md #8, #19, #21 item 6, and the author's working notes.
"""
import gzip
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

VOCAB = ('ok', 'EMPTY-RAW', 'CHALLENGE', 'PARSE-FAIL', 'BUDGET', 'KEY-402', 'RATE-429', 'TIMEOUT')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
BROWSER_HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
# Challenge signatures. Strong ones are interstitial TEXT that no real page carries in its
# first 4000 chars; they count at any status. Vendor and widget markers (a Turnstile embed,
# the DataDome or PerimeterX tag every page of a protected site loads in its <head>) count
# only on a blocking status or a short body, because a full 200 page legitimately carries
# them (verified: a 70 KB article that loads js.datadome.co is not a challenge).
CHALLENGE_STRONG = ('Just a moment', 'Verifying you are human', 'Verify you are human',
                    'Attention Required', 'Enable JavaScript and cookies',
                    'Checking your browser', 'Performing security verification',
                    'requiring CAPTCHA', 'px-captcha', '_Incapsula_')
CHALLENGE_WIDGET = ('cf-turnstile', 'challenges.cloudflare.com', 'PerimeterX', 'DataDome')
BLOCKING_STATUS = (401, 403, 429, 503)
SHORT_BODY = 30000
KEYFILES = (os.path.expanduser('~/.config/jina/api_key'),
)
JINA_BUDGET = 120000
ARCHIVE_PACE = 1.5
CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
DATA_NULL = re.compile(r'"data"\s*:\s*null')
# Proxy errors that a retry cannot change: the target name does not resolve, the URL
# itself is malformed, or the CSS selector matched nothing (422 "No content available for
# URL ... with target selector"). Everything else that carries data:null is transient.
DEFINITIVE = re.compile(r'ENOTFOUND|could not be resolved|not resolv|getaddrinfo|NAME_NOT_RESOLVED|'
                        r'ParamValidation|invalid url|ERR_CONNECTION_REFUSED|'
                        r'with target selector|No content available for URL|'
                        r'Suspicious action|non-public IP|Request to localhost', re.I)
DNS_WORDS = re.compile(r'ENOTFOUND|resolv|NAME_NOT|getaddrinfo', re.I)
SELECTOR_WORDS = re.compile(r'target selector|No content available for URL', re.I)
# The proxy refuses the target on policy (a private address, localhost): no retry, no rung 2.
REFUSED_WORDS = re.compile(r'Suspicious action|non-public IP|Request to localhost', re.I)
# A transient proxy error whose cause is a timeout at the proxy's browser (422
# AssertionFailureError with "TimeoutError: page.goto: Timeout 15000ms exceeded"): the
# skill's triage table files it under TIMEOUT, not EMPTY-RAW.
TIMEOUT_WORDS = re.compile(r'TimeoutError|timed? ?out|Timeout \d+ms', re.I)

_last_archive = 0.0
_key_cache = None


def trace(msg):
    print(msg, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------- key

def _bare_key(s):
    """The bare token: tolerate a 'JINA_API_KEY=' / 'export ...=' prefix and quotes."""
    s = s.strip()
    if s.lower().startswith('export '):
        s = s[7:].strip()
    if '=' in s and not s.startswith('jina_'):
        s = s.split('=', 1)[1].strip()
    return s.strip('\'"').strip()


def load_key():
    """Return (key, source). source is 'env', 'keyfile:<path>', or 'none'. Never print the key."""
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    k = _bare_key(os.environ.get('JINA_API_KEY', ''))
    if k:
        _key_cache = (k, 'env')
        return _key_cache
    override = os.environ.get('JINA_API_KEY_FILE')
    files = (override,) if override is not None else KEYFILES
    for p in files:
        try:
            k = _bare_key(open(p).read())
        except OSError:
            continue
        if k:
            _key_cache = (k, 'keyfile:' + p)
            return _key_cache
    _key_cache = ('', 'none')
    return _key_cache


def redact(s):
    key, _ = load_key()
    return s.replace(key, '<key>') if key else s


# ----------------------------------------------------------------------------- http

class Resp:
    __slots__ = ('status', 'body', 'headers', 'url', 'kind', 'err', 'secs')

    def __init__(self, status=0, body=b'', headers=None, url='', kind=None, err='', secs=0.0):
        self.status, self.body, self.headers = status, body, headers or {}
        self.url, self.kind, self.err, self.secs = url, kind, err, secs


def quote_url(u):
    # Leave existing percent-escapes and URL punctuation alone; encode spaces and non-ASCII.
    return urllib.parse.quote(u, safe="%/:?=&#+~@!$,;'()*[]")


def _classify_reason(reason):
    s = str(reason)
    if isinstance(reason, socket.gaierror) or 'nodename nor servname' in s or \
            'Name or service not known' in s or 'getaddrinfo' in s or \
            'Temporary failure in name resolution' in s:
        return 'dns'
    if isinstance(reason, (socket.timeout, TimeoutError)) or 'timed out' in s:
        return 'timeout'
    return 'conn'


CURL = shutil.which('curl')
# curl exit codes that name a cause (man curl): 6 resolve, 7 connect, 28 timeout, 18 partial.
CURL_KIND = {6: 'dns', 7: 'conn', 28: 'timeout', 18: 'truncated', 35: 'conn', 56: 'conn', 52: 'conn'}


def request(url, headers=None, timeout=30, method='GET', data=None):
    """One HTTP call. Never raises; the Resp carries status/body or kind/err.

    Transport is curl when present, urllib otherwise. Verified 2026-09-24 on
    findagrave.com/memorial/1/: identical headers, curl 200 (273,815 b), urllib 403
    "Just a moment". Cloudflare scores Python's TLS fingerprint below curl's, so the
    stdlib client would report CHALLENGE on UA-only walls that curl passes."""
    if CURL:
        return _request_curl(url, headers, timeout, method, data)
    return _request_urllib(url, headers, timeout, method, data)


def _cfg_quote(s):
    """A double-quoted curl config value: backslash and quote escaped, CR/LF removed."""
    s = re.sub(r'[\r\n]+', ' ', str(s))
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _request_curl(url, headers, timeout, method, data):
    t0 = time.monotonic()
    fd, body_path = tempfile.mkstemp(prefix='ladder-body-')
    os.close(fd)
    fd, cfg_path = tempfile.mkstemp(prefix='ladder-cfg-')
    # Headers AND the url travel in a 0600 curl config file (-K), never on argv: the
    # Authorization header and the dashboard URL (which carries api_key=) never show in ps.
    with os.fdopen(fd, 'w') as f:
        for k, v in (headers or {}).items():
            f.write(f'header = {_cfg_quote(f"{k}: {v}")}\n')
        f.write(f'url = {_cfg_quote(quote_url(url))}\n')
    os.chmod(cfg_path, 0o600)
    cmd = [CURL, '-sS', '-L', '--max-redirs', '10', '--compressed',
           '--connect-timeout', str(min(int(timeout), 20)), '--max-time', str(int(timeout)),
           '-K', cfg_path, '-o', body_path,
           '-w', '%{http_code}\n%{url_effective}\n%{content_type}\n']
    if data is not None:
        cmd += ['-X', method, '--data-binary', '@-']
    elif method != 'GET':
        cmd += ['-X', method]
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, timeout=int(timeout) + 10)
        rc, w, err = p.returncode, p.stdout.decode('utf-8', 'replace').split('\n'), p.stderr.decode('utf-8', 'replace').strip()
        with open(body_path, 'rb') as f:
            body = f.read()
    except subprocess.TimeoutExpired:
        rc, w, err, body = 28, ['0', url, ''], f'no response in {timeout}s', b''
    finally:
        for pth in (body_path, cfg_path):
            try:
                os.unlink(pth)
            except OSError:
                pass
    status = int(w[0]) if w and w[0].isdigit() else 0
    final = w[1] if len(w) > 1 and w[1] else url
    hdrs = {'Content-Type': w[2]} if len(w) > 2 and w[2] else {}
    kind = None
    if rc != 0:
        kind = CURL_KIND.get(rc, 'conn')
        err = re.sub(r'^curl: \(\d+\) ', '', err) or f'curl exit {rc}'
        if kind == 'timeout':
            err = f'no response in {timeout}s'
        if kind != 'truncated':
            status, body = (status if kind == 'truncated' else 0), (body if kind == 'truncated' else b'')
    if body[:2] == b'\x1f\x8b':
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
    return Resp(status, body, hdrs, final, kind, err, time.monotonic() - t0)


def _request_urllib(url, headers, timeout, method, data):
    req = urllib.request.Request(quote_url(url), data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    t0 = time.monotonic()
    status, body, hdrs, final, kind, err = 0, b'', {}, url, None, ''
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, hdrs, final = r.status, dict(r.headers), r.geturl()
            try:
                body = r.read()
            except http.client.IncompleteRead as e:
                body, kind, err = e.partial, 'truncated', 'connection closed mid-body'
            except (TimeoutError, socket.timeout):
                kind, err = 'timeout', f'read timed out after {timeout}s'
    except urllib.error.HTTPError as e:
        status, hdrs = e.code, dict(e.headers or {})
        try:
            body = e.read()
        except Exception:
            body = b''
    except urllib.error.URLError as e:
        kind, err = _classify_reason(e.reason), str(e.reason)
    except (TimeoutError, socket.timeout):
        kind, err = 'timeout', f'no response in {timeout}s'
    except Exception as e:  # ssl, protocol, remote-disconnect
        kind, err = 'conn', f'{type(e).__name__}: {e}'
    if body[:2] == b'\x1f\x8b':
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
    return Resp(status, body, hdrs, final, kind, err, time.monotonic() - t0)


def decode(r):
    ct = r.headers.get('Content-Type', '') if r.headers else ''
    m = re.search(r'charset=["\']?([\w.-]+)', ct, re.I)
    enc = m.group(1) if m else 'utf-8'
    try:
        return r.body.decode(enc, errors='replace')
    except LookupError:
        return r.body.decode('utf-8', errors='replace')


def as_json(raw):
    """Parse JSON that may arrive wrapped by the jina reader ('Markdown Content:\\n{...}')
    and peppered with control characters. Returns None when nothing parses."""
    if not raw:
        return None
    if 'Markdown Content:' in raw[:4000]:
        raw = raw.split('Markdown Content:', 1)[1]
    raw = CTRL.sub(' ', raw)
    starts = [i for i in (raw.find('{'), raw.find('[')) if i >= 0]
    if not starts:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[min(starts):].lstrip())
        return obj
    except Exception:
        return None


def challenge_signature(text, status=200):
    head = text[:4000]
    low = head.lower()
    for s in CHALLENGE_STRONG:
        if s.lower() in low:
            return s
    if status in BLOCKING_STATUS or len(text) < SHORT_BODY:
        for s in CHALLENGE_WIDGET:
            if s.lower() in low:
                return s
    return ''


# ----------------------------------------------------------------------------- html -> text

class _TextExtractor(HTMLParser):
    BLOCK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section',
             'article', 'header', 'footer', 'ul', 'ol', 'table', 'blockquote', 'pre', 'hr',
             'dt', 'dd', 'nav', 'aside', 'main', 'title'}
    SKIP = {'script', 'style', 'noscript', 'template', 'svg', 'head'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self.in_title = [], 0, '', False

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True
        elif tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append('\n')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append('\n')

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def html_to_text(html_src):
    p = _TextExtractor()
    try:
        p.feed(html_src)
        p.close()
    except Exception:
        pass
    text = ''.join(p.out)
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return p.title.strip(), text


def pdf_text(raw):
    if not shutil.which('pdftotext'):
        return None
    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.write(fd, raw)
    os.close(fd)
    try:
        out = subprocess.run(['pdftotext', '-layout', tmp, '-'], capture_output=True).stdout
    finally:
        os.unlink(tmp)
    return out.decode('utf-8', errors='replace')


# ----------------------------------------------------------------------------- rungs

class Outcome:
    def __init__(self, verdict, status=0, nbytes=0, content='', clause='', kind=None, title='',
                 tries=1, head='', final=''):
        assert verdict in VOCAB
        self.verdict, self.status, self.nbytes = verdict, status, nbytes
        self.content, self.clause, self.kind, self.title, self.tries = content, clause, kind, title, tries
        self.head, self.final = head, final  # first bytes as served (diagnose), final URL after redirects

    def line(self):
        return f'http {self.status or "-"} {self.nbytes}b -> {self.verdict} ({self.clause})'


def sample(text, n=200):
    """The first n chars of a body as one printable line (diagnose's 'read the raw bytes')."""
    return redact(re.sub(r'\s+', ' ', CTRL.sub(' ', text[:n * 2])).strip()[:n])


def rung1(url, timeout=30, fmt='markdown'):
    """Plain GET with browser headers. One variable (the UA) separates this from a bare curl."""
    r = request(url, BROWSER_HEADERS, timeout)
    n = len(r.body)
    if r.kind == 'timeout':
        return Outcome('TIMEOUT', 0, 0, '', f'no response in {timeout}s', kind='timeout')
    if r.kind == 'dns':
        return Outcome('EMPTY-RAW', 0, 0, '', 'host does not resolve (DNS)', kind='dns')
    if r.kind == 'conn':
        return Outcome('EMPTY-RAW', 0, 0, '', f'connection failed: {r.err}', kind='conn')
    text = decode(r)
    head = sample(text)
    moved = f', redirected to {r.url}' if r.url and r.url != url else ''
    if r.status == 429:
        return Outcome('RATE-429', r.status, n, '', 'http 429 from the origin (per-IP limit)', head=head, final=r.url)
    sig = challenge_signature(text, r.status)
    if sig:
        return Outcome('CHALLENGE', r.status, n, '', f'http {r.status}, signature "{sig}"{moved}', head=head, final=r.url)
    if r.status >= 400:
        return Outcome('EMPTY-RAW', r.status, n, '', f'http {r.status}, no challenge signature{moved}',
                       kind='target-error', head=head, final=r.url)
    if r.kind == 'truncated':
        return Outcome('PARSE-FAIL', r.status, n, '', 'body truncated mid-transfer', head=head, final=r.url)
    if not r.body.strip():
        return Outcome('EMPTY-RAW', r.status, 0, '', f'http {r.status}, empty body{moved}', final=r.url)
    ct = r.headers.get('Content-Type', '').lower()
    title = ''
    if r.body[:5] == b'%PDF-':
        content = pdf_text(r.body)
        if content is None:
            return Outcome('EMPTY-RAW', r.status, n, '', 'PDF body and no pdftotext on PATH', head=head, final=r.url)
    elif fmt == 'html' or ('html' not in ct and 'xml' not in ct and '<html' not in text[:2000].lower()):
        content = CTRL.sub(' ', text)  # raw html, json, plain text: delivered as served
    else:
        title, content = html_to_text(text)
        if title and fmt == 'markdown':
            content = f'# {title}\n\n{content}'
    if not content.strip():
        return Outcome('EMPTY-RAW', r.status, n, '', f'http {r.status}, {n}b with no text (JS shell?){moved}',
                       head=head, final=r.url)
    return Outcome('ok', r.status, n, content, f'http {r.status}, {n}b in {r.secs:.1f}s{moved}',
                   title=title, head=head, final=r.url)


def _jina_message(text):
    """The proxy's own one-line message: an error body's message/name, or a Warning: line."""
    d = as_json(text[:20000]) if text[:200].lstrip().startswith('{') else None
    msg = ''
    if isinstance(d, dict):
        msg = str(d.get('message') or d.get('readableMessage') or d.get('name') or '')
    if not msg:  # the error body was too long or too broken to parse: read the field itself
        m = re.search(r'"(?:message|readableMessage|name)"\s*:\s*"((?:[^"\\]|\\.){1,400})"', text[:20000])
        msg = m.group(1) if m else ''
    if not msg:
        m = re.search(r'^Warning:\s*(.+)$', text[:3000], re.M)
        msg = m.group(1) if m else ''
    return redact(re.sub(r'\s+', ' ', msg).strip()[:160])  # one line: the STATUS contract


def _unwrap_jina(text):
    title_m = re.search(r'^Title:\s*(.*)$', text[:3000], re.M)
    title = title_m.group(1).strip() if title_m else ''
    m = re.search(r'(?:^|\n)(?:Markdown|Text|HTML|Raw) Content:[ \t]*\n?', text[:4000])
    content = text[m.end():] if m else text
    return title, CTRL.sub(' ', content)


def rung2_once(url, key, fmt='markdown', selector=None, timeout=90, budget=JINA_BUDGET):
    """One r.jina.ai call with the proven header set. Returns (Outcome, retryable)."""
    hdrs = {'X-Engine': 'browser', 'X-No-Cache': 'true', 'X-Token-Budget': str(budget),
            'X-Return-Format': fmt}
    if key:
        hdrs['Authorization'] = 'Bearer ' + key
    if selector:
        hdrs['X-Target-Selector'] = selector
    r = request('https://r.jina.ai/' + url, hdrs, timeout)
    n = len(r.body)
    if r.kind == 'timeout':
        return Outcome('TIMEOUT', 0, 0, '', f'r.jina.ai gave no response in {timeout}s', kind='timeout'), True
    if r.kind in ('dns', 'conn'):
        return Outcome('EMPTY-RAW', 0, 0, '', f'r.jina.ai unreachable: {r.err}', kind='conn'), True
    text = decode(r)
    head = sample(text)
    msg = _jina_message(text)
    if r.status == 402:
        return Outcome('KEY-402', 402, n, '', 'http 402: key balance exhausted (top up)', kind='key', head=head), False
    if r.status == 401:
        return Outcome('KEY-402', 401, n, '', f'http 401: key missing or rejected ({msg})', kind='key', head=head), False
    if r.status == 429:
        return Outcome('RATE-429', 429, n, '', f'proxy http 429 ({msg})', head=head), True
    if r.status == 409 or 'BudgetExceededError' in text[:400]:
        return Outcome('BUDGET', r.status, n, '', 'over X-Token-Budget; shrink the request '
                       '(--selector or a narrower URL), never raise the budget', kind='budget', head=head), False
    if DATA_NULL.search(text[:200]):
        probe = msg or text[:3000]
        if DEFINITIVE.search(probe):
            if SELECTOR_WORDS.search(probe):
                return Outcome('EMPTY-RAW', r.status, n, '', f'the selector matched nothing: {msg}',
                               kind='selector', head=head), False
            if REFUSED_WORDS.search(probe):
                return Outcome('EMPTY-RAW', r.status, n, '', f'the proxy refuses this target: {msg}',
                               kind='refused', head=head), False
            return Outcome('EMPTY-RAW', r.status, n, '', f'proxy error, not transient: {msg}',
                           kind='dns' if DNS_WORDS.search(probe) else 'target-error', head=head), False
        if TIMEOUT_WORDS.search(probe):
            return Outcome('TIMEOUT', r.status, n, '', f'the proxy timed out reaching the origin ({msg})',
                           kind='timeout', head=head), True
        return Outcome('EMPTY-RAW', r.status, n, '', f'transient proxy error ({msg or "data:null"})', head=head), True
    if r.status >= 500:
        return Outcome('EMPTY-RAW', r.status, n, '', f'proxy http {r.status} ({msg})', head=head), True
    if r.status >= 400:
        return Outcome('EMPTY-RAW', r.status, n, '', f'proxy http {r.status}, target error passed through ({msg})',
                       kind='target-error', head=head), False
    if not text.strip():
        return Outcome('EMPTY-RAW', r.status, 0, '', 'proxy http 200 with an empty body'), True
    sig = challenge_signature(text, r.status)
    if sig:
        return Outcome('CHALLENGE', r.status, n, '', f'the proxy itself caught the challenge ("{sig}"); stochastic',
                       head=head), True
    if r.kind == 'truncated':
        return Outcome('PARSE-FAIL', r.status, n, '', 'proxy body truncated mid-transfer', head=head), True
    tgt = re.search(r'Target URL returned error (\d{3})', msg)
    if tgt and int(tgt.group(1)) >= 400:
        return Outcome('EMPTY-RAW', int(tgt.group(1)), n, '', f'proxy reached the origin, which answered: {msg}',
                       kind='target-error', head=head), False
    title, content = _unwrap_jina(text)
    if not content.strip():
        return Outcome('EMPTY-RAW', r.status, n, '', 'proxy returned a header block with no content', head=head), True
    warn = f'; proxy warning: {msg}' if msg else ''
    return Outcome('ok', r.status, n, content, f'proxy http 200, {n}b in {r.secs:.1f}s{warn}',
                   title=title, head=head), False


def rung2(url, key, fmt='markdown', selector=None, timeout=90, tries=4, budget=JINA_BUDGET):
    last = None
    for i in range(tries):
        o, retry = rung2_once(url, key, fmt, selector, timeout, budget)
        o.tries = i + 1
        trace(f'# rung=2 try {i + 1}/{tries}: {o.line()}')
        if o.verdict == 'ok' or not retry:
            return o
        last = o
        if i < tries - 1:
            wait = 4 + 3 * i
            trace(f'# rung=2 backoff {wait}s (one variable: pacing)')
            time.sleep(wait)
    last.clause += f' after {tries} tries'
    return last


def stealth_command(url):
    return (f'stealth_fetch(url="{url}")  [seleniumbase-stealth MCP; cdp_fetch if still challenged; '
            f'or the /stealth skill]')


def next_move(o, url, prior=None):
    """The one next move for a final outcome o; prior is rung 1's outcome when it ran."""
    v = o.verdict
    if v == 'CHALLENGE':
        return 'rung 5 (stealth, walls only): ' + stealth_command(url)
    if v == 'KEY-402':
        return 'python3 ladder.py health; top up the key, then --rung 2'
    if v == 'BUDGET':
        return f'python3 ladder.py fetch "{url}" --rung 2 --selector "<css>" (shrink the request; never raise the budget)'
    if v == 'RATE-429':
        return f'wait seconds, not minutes, then ONE retry: python3 ladder.py fetch "{url}" --rung 2'
    if v == 'TIMEOUT':
        return f'ONE retry with a longer timeout: python3 ladder.py fetch "{url}" --rung 2 --timeout 180'
    if v == 'PARSE-FAIL':
        return 'ONE retry (truncated transfer); if it repeats, --selector to shrink the page'
    if o.kind == 'selector':
        return 'fix the --selector (it matched nothing on the rendered page); not a retry'
    if o.kind == 'refused':
        return 'the proxy will not fetch this target (private address or policy); rung 2 does not apply, use rung 1 or a public URL'
    if o.kind == 'dns':
        return 'fix the URL; the host does not resolve, no rung helps'
    if o.kind == 'target-error':
        if prior is not None and prior.status == o.status:
            return f'the origin answers http {o.status} through both rungs; check the URL, not the channel'
        return f'the origin answered http {o.status} to the proxy; check the URL, not the channel'
    return 'ONE retry, then rung 5 only if the body is a challenge shell: ' + stealth_command(url)


# ----------------------------------------------------------------------------- fetch

def _parse_fetch(argv):
    opts = {'url': None, 'rung': 1, 'out': None, 'max_chars': 0, 'selector': None,
            'format': 'markdown', 'timeout': None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('--rung', '--out', '--max-chars', '--selector', '--format', '--timeout'):
            if i + 1 >= len(argv):
                return None
            val = argv[i + 1]
            k = a[2:].replace('-', '_')
            try:
                if k in ('rung', 'max_chars'):
                    val = int(val)
                elif k == 'timeout':
                    val = float(val)
            except ValueError:
                return None
            opts[k] = val
            i += 2
        elif a.startswith('--'):
            return None
        elif opts['url'] is None:
            opts['url'] = a
            i += 1
        else:
            return None
    if not opts['url'] or opts['format'] not in ('markdown', 'text', 'html') or opts['rung'] not in (1, 2, 5):
        return None
    if opts['max_chars'] < 0 or (opts['timeout'] is not None and opts['timeout'] <= 0):
        return None
    if opts['selector'] and opts['rung'] == 1:
        opts['rung'] = 2  # only the proxy honors X-Target-Selector; rung 1 would ignore it silently
        opts['selector_bump'] = True
    return opts


def _emit(o, rung, opts, clause):
    content = o.content
    mc = opts['max_chars']
    if mc and len(content) > mc:
        clause += f'; truncated to {mc} of {len(content)} chars'
        content = content[:mc]
    out = opts['out']
    if out:
        try:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(content)
            clause += f'; wrote {len(content)} chars to {out}'
        except OSError as e:
            clause += f'; could not write {out} ({e.strerror or e}); content follows on stdout'
            out = None
    print(f'# STATUS: ok | rung={rung} | {clause}', flush=True)
    if not out:
        sys.stdout.write(content)
        if not content.endswith('\n'):
            sys.stdout.write('\n')
        sys.stdout.flush()
    return 0


def cmd_fetch(argv):
    opts = _parse_fetch(argv)
    if not opts:
        print(__doc__)
        return 3
    url = opts['url']
    if not re.match(r'^https?://', url):
        url = 'https://' + url
    key, src = load_key()
    outcomes = {}
    if opts.get('selector_bump'):
        trace('# --selector applies at rung 2 only (X-Target-Selector); starting there')
    if opts['rung'] == 1:
        o = rung1(url, opts['timeout'] or 30, opts['format'])
        outcomes[1] = o
        trace(f'# rung=1: {o.line()}')
        if o.verdict == 'ok':
            return _emit(o, 1, opts, o.clause)
    if opts['rung'] <= 2:
        if not key:
            trace('# rung=2: no key (env, ~/.config/jina/api_key, JINA_API_KEY_FILE); anonymous tier')
        o = rung2(url, key, opts['format'], opts['selector'], opts['timeout'] or 90)
        outcomes[2] = o
        if o.verdict == 'ok':
            prior = f'rung 1 {outcomes[1].verdict} ({outcomes[1].clause}); ' if 1 in outcomes else ''
            passed = f'jina browser engine passed on try {o.tries}/4' if o.tries > 1 else 'jina browser engine passed'
            return _emit(o, 2, opts, f'{prior}{passed}; {o.clause}')
    if opts['rung'] == 5:
        print(f'# STATUS: CHALLENGE | rung=5 | this script does not drive a browser; run {stealth_command(url)}')
        return 2
    top = max(outcomes)
    final = outcomes[top]
    prior = '; '.join(f'rung {k} {v.verdict} ({v.clause})' for k, v in sorted(outcomes.items()) if k != top)
    parts = [p for p in (prior, f'rung {top} {final.clause}',
                         'next: ' + next_move(final, url, outcomes.get(1) if top != 1 else None)) if p]
    print(f'# STATUS: {final.verdict} | rung={top} | ' + '; '.join(parts))
    return 2


# ----------------------------------------------------------------------------- search (s.jina.ai)

def cmd_search(argv):
    if not argv:
        print(__doc__)
        return 3
    query = argv[0]
    try:
        num = int(argv[1]) if len(argv) > 1 else 10
    except ValueError:
        num = 0
    if not query.strip() or num < 1 or len(argv) > 2:
        print(__doc__)
        return 3
    key, _ = load_key()
    hdrs = {'Content-Type': 'application/json', 'Accept': 'application/json',
            'X-Respond-With': 'no-content'}
    if key:
        hdrs['Authorization'] = 'Bearer ' + key
    r = request('https://s.jina.ai/', hdrs, 60, 'POST', json.dumps({'q': query, 'num': num}).encode())
    if r.kind == 'timeout':
        print('# STATUS: TIMEOUT | rung=3 | s.jina.ai gave no response in 60s; ONE retry')
        return 2
    if r.kind:
        print(f'# STATUS: EMPTY-RAW | rung=3 | s.jina.ai unreachable: {r.err}; ONE retry')
        return 2
    text = decode(r)
    msg = _jina_message(text)
    if r.status in (401, 402):
        print(f'# STATUS: KEY-402 | rung=3 | http {r.status}: {msg or "key exhausted or rejected"}; run health')
        return 2
    if r.status == 429:
        print(f'# STATUS: RATE-429 | rung=3 | s.jina.ai http 429 ({msg}); wait seconds, ONE retry')
        return 2
    if r.status >= 400:
        print(f'# STATUS: EMPTY-RAW | rung=3 | s.jina.ai http {r.status} ({msg}); ONE retry')
        return 2
    d = as_json(text)
    if not isinstance(d, dict):
        print(f'# STATUS: PARSE-FAIL | rung=3 | raw {len(r.body)}b, head {text[:80]!r}; ONE retry')
        return 2
    hits = d.get('data') or d.get('results') or []
    print(f'# STATUS: ok | rung=3 | {len(hits)} hit(s) for: {query}' +
          ('' if hits else ' (genuine zero from the open-web index)'))
    for h in hits:
        print(f"- {str(h.get('title', '')).strip()[:100]}\n  {h.get('url', '')}")
    return 0


# ----------------------------------------------------------------------------- wayback

def pace():
    global _last_archive
    wait = ARCHIVE_PACE - (time.monotonic() - _last_archive)
    if wait > 0:
        time.sleep(wait)
    _last_archive = time.monotonic()


def archive_get(url, key, timeout=40, empty_ok=False):
    """The variation ladder for one archive.org call: direct http, direct https (one
    variable), then the SAME URL through r.jina.ai (a different IP pool) on 429/empty/5xx.
    Returns (text, channel, error)."""
    global _last_archive
    attempts = [('direct http', url)]
    if url.startswith('http://'):
        attempts.append(('direct https', 'https://' + url[7:]))
    errs = []
    limited = False
    for label, u in attempts:
        for attempt in (1, 2):
            pace()
            r = request(u, {'User-Agent': UA}, timeout)
            _last_archive = time.monotonic()
            text = decode(r)
            if r.status == 200 and (text.strip() or empty_ok):
                return text, label, ''
            why = f'http {r.status}' if r.status else (r.kind or 'error')
            if r.status == 200:
                why += ' empty'
            if attempt == 1 and r.status in (200, 503):
                # wayback_gate's paced retry: the same call once more, 8 s later (one variable)
                trace(f'#   archive.org {label}: {why} -> same call once more in 8s')
                time.sleep(8)
                continue
            errs.append(f'{label} {why}')
            trace(f'#   archive.org {label}: {why} -> next variable')
            break
        if r.status == 429:
            limited = True
            break  # the per-IP limit: the next variable is the IP pool, not the scheme
    if not key:
        return '', 'none', '; '.join(errs) + '; no jina key for the go-around'
    hdrs = {'Authorization': 'Bearer ' + key, 'X-No-Cache': 'true', 'X-Token-Budget': '60000'}
    r = request('https://r.jina.ai/' + url, hdrs, 60)
    text = decode(r)
    msg = _jina_message(text)
    origin = re.search(r'Target URL returned error (\d{3})', msg)
    offline = 'Temporarily Offline' in text[:600]
    if r.status == 200 and text.strip() and not DATA_NULL.search(text[:200]) and not origin and not offline:
        return text, 'via r.jina.ai', ''
    if origin or offline:
        errs.append(f'via r.jina.ai: archive.org answered {msg or "503 Internet Archive: Temporarily Offline"}'
                    + ('' if limited else ' (the origin, not the IP, is the problem)'))
    else:
        errs.append(f'via r.jina.ai http {r.status} {msg}'.strip())
    return '', 'none', '; '.join(errs)


def expand(spec):
    m = re.match(r'^lccn:([a-z0-9]+):(\d{4}-\d{2}-\d{2}):(\d+)$', spec)
    if not m:
        return [spec]
    lccn, date, sp = m.groups()
    return [f'chroniclingamerica.loc.gov/lccn/{lccn}/{date}/ed-1/seq-{sp}/',
            f'www.loc.gov/resource/{lccn}/{date}/ed-1/?sp={sp}']


def availability(u, key):
    text, chan, err = archive_get('http://archive.org/wayback/available?url=' +
                                  urllib.parse.quote(u, safe=''), key)
    if not text:
        return {'error': err}, chan
    d = as_json(text)
    if not isinstance(d, dict):
        return {'error': f'{chan}: unparseable ({text[:60]!r})'}, chan
    return d.get('archived_snapshots', {}).get('closest'), chan


def cdx(u, key, wildcard=True):
    q = urllib.parse.quote(u, safe='') + ('*' if wildcard else '')
    # With output=json the CDX answers "[]" (3 bytes) when nothing is captured; an empty
    # body is therefore a channel failure, never a clear.
    text, chan, err = archive_get(f'http://web.archive.org/cdx/search/cdx?url={q}&output=json&limit=40', key)
    if chan == 'none':
        return [['CDX-ERR', err]], chan
    rows = as_json(text)
    if not isinstance(rows, list):
        return [['CDX-ERR', f'unparseable ({text[:60]!r})']], chan
    return rows[1:] if len(rows) > 1 else [], chan


def _page_key(u):
    """(path without scheme or trailing slash, sp) for a loc.gov-style URL. The www viewer
    form addresses a page by ?sp=N and a bare /ed-1/ is page 1 (the UMFRIED capture), so
    the sp value is part of the page identity and the rest of the query is not."""
    u = re.sub(r'^https?://', '', u)
    path, _, query = u.partition('?')
    sp = urllib.parse.parse_qs(query).get('sp', ['1'])[0]
    return path.rstrip('/'), sp


def same_page(orig, target):
    """True when a CDX row's original URL is the target page itself or one of its own
    renditions (target/, target/ocr/, target.pdf, target?sp=N&st=text); False for a sibling
    the wildcard also matched (seq-10/ for seq-1/, ?sp=2 for ?sp=1)."""
    op, osp = _page_key(orig)
    tp, tsp = _page_key(target)
    return osp == tsp and (op == tp or op.startswith(tp + '/') or op.startswith(tp + '.'))


def grep_capture(ts, orig, toks):
    """Pull one capture (raw, no toolbar) and count the tokens in its rendered text.
    Returns (counts, size, kind) with kind in html | pdf-text-extracted | binary | error.
    A transport error or 5xx gets the same call once more 8 s later over https (one
    variable: web.archive.org refuses port 80 after a burst of pulls, verified 2026-09-24)."""
    global _last_archive
    for scheme in ('http', 'https'):
        pace()
        r = request(f'{scheme}://web.archive.org/web/{ts}id_/{orig}', {'User-Agent': UA}, 120)
        _last_archive = time.monotonic()
        if not (r.kind or r.status >= 500) or scheme == 'https':
            break
        trace(f'#   capture {ts}: {r.kind or "http " + str(r.status)} {r.err} -> same call over https in 8s')
        time.sleep(8)
    raw = r.body
    if r.kind or r.status != 200:
        why = f'http {r.status}' if r.status else (r.kind or 'error')
        return {}, len(raw), f'error: {why} {r.err}'.strip()
    if raw[:5] == b'%PDF-':
        txt = pdf_text(raw)
        if txt:
            norm = txt.lower()
            counts = {t: norm.count(t.lower()) for t in toks}
            counts['_pdftext'] = len(txt)
            return counts, len(raw), 'pdf-text-extracted'
        return {t: 0 for t in toks}, len(raw), 'binary'
    binary = b'\x00' in raw[:400]
    cap = raw.decode('utf-8', errors='replace')
    norm = re.sub(r'<br\s*/?>', ' ', cap, flags=re.I)
    norm = re.sub(r'<[^>]+>', ' ', norm).lower()
    counts = {t: norm.count(t.lower()) for t in toks}
    return counts, len(raw), 'binary' if binary else 'html'


def cmd_wayback(argv):
    args = list(argv)
    toks = []
    if '--grep' in args:
        i = args.index('--grep')
        if i + 1 >= len(args):
            print(__doc__)
            return 3
        toks = [t for t in args[i + 1].split(',') if t]
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 3
    key, _ = load_key()
    urls = [u for a in args for u in expand(re.sub(r'^https?://', '', a))]
    hot = err = False
    kills = siblings = 0
    report = []  # stdout is held back so the STATUS line (the verdict) is printed first
    out = report.append
    for u in urls:
        out(f'== {u}')
        trace(f'# wayback: {u}')
        s, chan = availability(u, key)
        if s and 'error' in s:
            err = True
            out(f'   availability: CHANNEL-ERR ({s["error"][:120]}) -- 429 = per-IP limit; the go-around '
                f'already ran; re-run in seconds, not minutes')
        else:
            out(f'   availability [{chan}]: {"none" if not s else s}')
        rows, chan = cdx(u, key)
        if rows and rows[0][0] == 'CDX-ERR':
            err = True  # a CDX error must NEVER fall through to FULL MARGIN
            out(f'   CDX: ERR {rows[0][1][:120]} (re-run the gate)')
            continue
        if not rows:
            out(f'   CDX wildcard [{chan}]: []')
            continue
        if not any(same_page(r[2], u) for r in rows):
            # the wildcard matched only siblings (seq-10/ for seq-1/): listed, never the target
            out(f'   CDX wildcard [{chan}]: {len(rows)} row(s), none of them the target page (siblings only)')
        hot = True
        seen = {}
        for r in rows:
            ts, orig, st = r[1], r[2], (r[4] if len(r) > 4 else '?')
            digest = r[5] if len(r) > 5 else ''
            if not same_page(orig, u):
                # the wildcard's over-match: another page of the issue. Listed so the
                # over-match is visible; never pulled (the EZELL-precedent pass), which
                # also keeps the pull count under archive.org's per-IP connection limit.
                siblings += 1
                out(f'   SIBLING {ts} {st} {orig[:90]} (not the target page; not pulled)')
                continue
            out(f'   CAPTURE {ts} {st} {orig[:90]}')
            if not (toks and st == '200'):
                continue
            if digest and digest in seen:
                out(f'     same digest as {seen[digest]}, not re-pulled')
                continue
            seen[digest] = ts
            trace(f'#   pull {ts} {orig[:80]}')
            counts, size, kind = grep_capture(ts, orig, toks)
            if kind.startswith('error'):
                err = True
                out(f'     pull FAILED ({kind}); this capture is NOT cleared')
                continue
            kill = any(v > 0 for k, v in counts.items() if not k.startswith('_'))
            kills += kill
            verdict = ('TOKEN-RENDER = KILL-GRADE' if kill else
                       ('BINARY capture (pdf/image): raw-byte grep 0 does NOT clear it; grade as the '
                        'giant-file margin channel' if kind == 'binary' else
                        'token-free (metadata-only = clear)'))
            out(f'     pull({size}b, {kind}) grep: {counts} -> {verdict}')
    if hot:
        verdict = ('VERDICT: CAPTURES EXIST -- adjudicate per the content law' +
                   (f'; {kills} target capture(s) render the tokens (KILL-GRADE)' if toks else '') +
                   (f'; {siblings} sibling row(s) listed, not pulled' if siblings else '') +
                   (' (a channel also errored; re-run it before grading)' if err else ''))
        rc = 0
    elif err:
        verdict = 'VERDICT: GATE INCOMPLETE (a channel errored; NEVER read this as clear -- re-run the erred channel)'
        rc = 2
    else:
        verdict = 'VERDICT: FULL MARGIN (no captures on any channel)'
        rc = 0
    print(f'# STATUS: {"EMPTY-RAW" if rc else "ok"} | rung=4 | {verdict}')
    for line in report:
        print(line)
    print(verdict)
    return rc


# ----------------------------------------------------------------------------- health

def _find(d, name):
    if isinstance(d, dict):
        if name in d:
            return d[name]
        for v in d.values():
            f = _find(v, name)
            if f is not None:
                return f
    elif isinstance(d, list):
        for v in d:
            f = _find(v, name)
            if f is not None:
                return f
    return None


def cmd_health(argv):
    key, src = load_key()
    lines = [f'key: {"present" if key else "MISSING"} | source: {src}']  # printed after the STATUS line

    def done(status, rc):
        print(status)
        for line in lines:
            print(line)
        return rc

    if not key:
        return done('# STATUS: KEY-402 | rung=2 | no key in env, ~/.config/jina/api_key, or JINA_API_KEY_FILE '
                    '(or JINA_API_KEY_FILE names an empty path)', 2)
    # The dashboard needs api_key= in the query (a bare Authorization header answers 422,
    # verified 2026-09-24); request() keeps that URL in the 0600 config file, off argv.
    r = request(f'https://embeddings-dashboard-api.jina.ai/api/v1/api_key/user?api_key={key}',
                {'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}, 30)
    bal = None
    if r.kind:
        lines.append(f'balance: unreachable ({redact(r.err)})')
    else:
        d = as_json(decode(r))
        wallet = _find(d, 'wallet') if d is not None else None
        bal = wallet.get('total_balance') if isinstance(wallet, dict) else _find(d, 'total_balance')
        lines.append(f'balance: http {r.status} | wallet.total_balance = {bal}')
        if r.status == 402:
            return done('# STATUS: KEY-402 | rung=2 | dashboard answered 402: balance exhausted, top up', 2)
        if r.status in (401, 403, 422):
            lines.append(f'  dashboard rejected the key: {sample(decode(r), 120)}')
    probe, _ = rung2_once('https://example.com', key, 'markdown', None, 45, 5000)
    lines.append(f'reader probe (example.com): {redact(probe.line())}')
    if probe.verdict == 'KEY-402':
        return done(f'# STATUS: KEY-402 | rung=2 | {probe.clause}', 2)
    if probe.verdict != 'ok':
        return done(f'# STATUS: {probe.verdict} | rung=2 | probe failed: {probe.clause}; ONE retry', 2)
    low = isinstance(bal, (int, float)) and bal < 1_000_000
    return done(f'# STATUS: ok | rung=2 | key accepted, balance {bal}' + ('; LOW, plan a top-up' if low else ''), 0)


# ----------------------------------------------------------------------------- diagnose

def cmd_diagnose(argv):
    if len(argv) != 1:
        print(__doc__)
        return 3
    url = argv[0]
    if not re.match(r'^https?://', url):
        url = 'https://' + url
    key, src = load_key()
    o1 = rung1(url, 20)
    trace(f'# rung=1: {o1.line()}')
    o2 = rung2(url, key, 'markdown', None, 20, tries=1)
    q = f'"{url}"'
    if o1.verdict == 'ok':
        rec, cmd = 'none (rung 1 serves the page)', f'python3 ladder.py fetch {q}'
    elif o2.verdict == 'ok':
        rec, cmd = '2 (jina reader)', f'python3 ladder.py fetch {q} --rung 2'
    elif o2.verdict == 'KEY-402':
        rec, cmd = '2 after the key is fixed', 'python3 ladder.py health'
    elif o2.verdict == 'BUDGET':
        rec, cmd = '2 with a smaller request', f'python3 ladder.py fetch {q} --rung 2 --selector "<css>"'
    elif o2.verdict == 'TIMEOUT':
        rec, cmd = '2 with a real timeout (diagnose allows 20 s; the browser engine often needs more)', \
                   f'python3 ladder.py fetch {q} --rung 2 --timeout 180'
    elif o2.verdict == 'RATE-429':
        rec, cmd = '2, ONE retry after seconds', f'python3 ladder.py fetch {q} --rung 2'
    elif o2.verdict == 'CHALLENGE' or o1.verdict == 'CHALLENGE':
        rec, cmd = '5 (stealth; a genuine wall)', stealth_command(url)
    elif o1.kind == 'dns' and o2.kind in ('dns', 'target-error'):
        rec, cmd = 'none: fix the URL (the host does not resolve for either channel)', '(none)'
    elif o2.kind == 'target-error':
        rec, cmd = f'none: the origin answers http {o2.status} on both rungs; check the URL', '(none)'
    else:
        rec, cmd = '2, ONE retry; then 5 only if the body is a challenge shell', \
                   f'python3 ladder.py fetch {q} --rung 2'
    # The STATUS line is the table's conclusion: the cheapest rung that serves the page,
    # else the deepest rung's verdict with the recommendation as the next move.
    if o1.verdict == 'ok':
        status = f'# STATUS: ok | rung=1 | {o1.clause}; next: {cmd}'
    elif o2.verdict == 'ok':
        status = f'# STATUS: ok | rung=2 | rung 1 {o1.verdict} ({o1.clause}); {o2.clause}; next: {cmd}'
    else:
        status = f'# STATUS: {o2.verdict} | rung=2 | rung 1 {o1.verdict} ({o1.clause}); rung 2 {o2.clause}; next rung {rec}: {cmd}'
    print(status)
    print('rung | http | bytes  | verdict')
    print(f'1    | {str(o1.status or "-"):<4} | {o1.nbytes:<6} | {o1.verdict} ({o1.clause})')
    print(f'     | first 200 bytes: {o1.head or "(none)"}')
    print(f'2    | {str(o2.status or "-"):<4} | {o2.nbytes:<6} | {o2.verdict} ({o2.clause})')
    print(f'     | first 200 bytes: {o2.head or "(none)"}')
    print(f'next rung: {rec}')
    print(f'next command: {cmd}')
    return 0 if 'ok' in (o1.verdict, o2.verdict) else 2


# ----------------------------------------------------------------------------- main

def main(argv):
    try:
        sys.stdout.reconfigure(errors='replace', line_buffering=True)
    except Exception:
        pass
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 3
    cmds = {'fetch': cmd_fetch, 'search': cmd_search, 'wayback': cmd_wayback,
            'health': cmd_health, 'diagnose': cmd_diagnose}
    fn = cmds.get(argv[0])
    if not fn:
        print(__doc__)
        return 3
    try:
        return fn(argv[1:])
    except KeyboardInterrupt:
        print('# STATUS: TIMEOUT | rung=- | interrupted by the user')
        return 2
    except Exception as e:  # the instrument itself broke: still one STATUS line, never a bare traceback
        import traceback
        traceback.print_exc()
        print(f'# STATUS: PARSE-FAIL | rung=- | internal error {type(e).__name__}: {redact(str(e))[:200]}; '
              f'traceback on stderr, report it')
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
