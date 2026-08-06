#!/usr/bin/env python3
"""Fetch Ocado product pages on behalf of the weekly price routine.

Ocado serves a residential connection and returns 403 to datacenter IPs, so
neither the routine's sandbox nor WebFetch can reach it. This runs on a machine
that Ocado does answer, and relays exactly one kind of request:

    GET /ocado/<slug>/<id>   ->   https://www.ocado.com/products/<slug>/<id>

Nothing else. The caller never supplies a URL, host, scheme, port or query, so
there is no parameter to point at a private address -- this cannot be used as
an open relay or an SSRF lever, only to read Ocado product pages.

Also enforced:
  * bearer token, compared in constant time; the service refuses to start
    without one
  * GET only, one fixed path shape, strict slug/id character classes
  * client headers are discarded, not forwarded
  * upstream redirects are refused rather than followed
  * response size and request rate are capped

Bind it to localhost and put TLS in front (see ocado-proxy.service and the
notes in .routine/README.md). The token is a bearer credential: over plain
HTTP anyone on the path can lift it and use it.

Stdlib only, no dependencies.
"""

import hmac
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("OCADO_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("OCADO_PROXY_PORT", "8787"))
TOKEN = os.environ.get("OCADO_PROXY_TOKEN", "")

UPSTREAM = "https://www.ocado.com/products/{}/{}"
# The whole of the caller's influence over the outbound request.
PATH = re.compile(r"^/ocado/([a-z0-9][a-z0-9-]{0,119})/([0-9]{1,15})$")

TIMEOUT = 20
MAX_BYTES = 2 * 1024 * 1024
# The routine needs 13 pages a week. This is generous and still bounds what a
# leaked token could do.
RATE_LIMIT = 60
RATE_WINDOW = 3600

UA = "Mozilla/5.0 (compatible; food-finder/1.0; personal weekly price comparison)"

_hits = deque()
_lock = threading.Lock()


def rate_ok():
    now = time.monotonic()
    with _lock:
        while _hits and now - _hits[0] > RATE_WINDOW:
            _hits.popleft()
        if len(_hits) >= RATE_LIMIT:
            return False
        _hits.append(now)
        return True


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect means Ocado is sending us somewhere we did not vet."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect)


class Handler(BaseHTTPRequestHandler):
    server_version = "ocado-proxy"
    sys_version = ""

    def reply(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorised(self):
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return hmac.compare_digest(header[len(prefix):], TOKEN)

    def do_GET(self):
        if not self.authorised():
            self.reply(401, b"unauthorised\n")
            return

        m = PATH.match(self.path)
        if not m:
            self.reply(404, b"not a product path\n")
            return

        if not rate_ok():
            self.reply(429, b"rate limited\n")
            return

        url = UPSTREAM.format(m.group(1), m.group(2))
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                body = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            # Ocado's own answer -- 403, 404, whatever. Pass the code on so the
            # caller can tell "blocked" from "no such product".
            self.log_message("upstream %s -> %s", url, e.code)
            self.reply(e.code, f"upstream {e.code}\n".encode())
            return
        except (urllib.error.URLError, TimeoutError) as e:
            self.log_message("upstream %s -> %s", url, e)
            self.reply(502, b"upstream unreachable\n")
            return

        if len(body) > MAX_BYTES:
            self.reply(502, b"upstream response too large\n")
            return

        self.reply(200, body, "text/html; charset=utf-8")

    def do_POST(self):
        self.reply(405, b"GET only\n")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_CONNECT = do_OPTIONS = do_POST

    def log_message(self, fmt, *args):
        # Never log the Authorization header; BaseHTTPRequestHandler would not,
        # but be explicit about what does get written.
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main():
    if not TOKEN:
        sys.exit("OCADO_PROXY_TOKEN is not set -- refusing to start")
    if len(TOKEN) < 32:
        sys.exit("OCADO_PROXY_TOKEN is too short -- use at least 32 characters")
    print(f"listening on {HOST}:{PORT}", file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
