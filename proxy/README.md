# Ocado relay

Ocado returns 403 to datacenter IPs. The weekly routine runs on one, so it
cannot read Ocado at all — not from Bash, and not through WebFetch either.
This service runs where Ocado does answer and relays its product pages.

It is deliberately not a proxy in the general sense. The caller sends a slug
and a numeric id; the host, scheme and path are hardcoded here:

    GET /ocado/<slug>/<id>   ->   https://www.ocado.com/products/<slug>/<id>

There is no parameter naming a destination, so it cannot be pointed at a link
local address, a LAN host, or anything else on the internet.

## Deploy

    sudo install -d -m 755 /opt/food-finder/proxy
    sudo install -m 755 ocado_proxy.py /opt/food-finder/proxy/
    sudo install -m 644 ocado-proxy.service /etc/systemd/system/

    sudo install -d -m 700 /etc/ocado-proxy
    printf 'OCADO_PROXY_TOKEN=%s\n' "$(openssl rand -hex 32)" \
        | sudo tee /etc/ocado-proxy/env > /dev/null
    sudo chmod 600 /etc/ocado-proxy/env

    sudo systemctl daemon-reload
    sudo systemctl enable --now ocado-proxy

Check it, reading the token back out of the file rather than retyping it:

    TOKEN=$(sudo sed -n 's/^OCADO_PROXY_TOKEN=//p' /etc/ocado-proxy/env)
    curl -sSD- -o/dev/null http://127.0.0.1:8787/ocado/ocado-organic-carrots/627742011 \
        -H "Authorization: Bearer $TOKEN"

`HTTP/1.0 200 OK` means it works. `401` means the token did not match, `502`
means Ocado refused this machine too — check `journalctl -u ocado-proxy` for
the upstream status. No output at all means nothing is listening; `-sS` is
what keeps that error visible rather than silent.

## Update after a git pull

The deployed copy under `/opt` is exactly that — a copy. `git pull` in your
checkout changes nothing the daemon is running, so reinstall and restart:

    git pull
    sudo install -m 755 proxy/ocado_proxy.py /opt/food-finder/proxy/
    sudo install -m 644 proxy/ocado-proxy.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl restart ocado-proxy

Reinstalling both files every time is deliberate: `install` overwrites in
place, `daemon-reload` is cheap, and doing it unconditionally means never
having to work out whether this particular pull touched the unit file. Skip
`daemon-reload` after a unit change and systemd keeps running the old
definition without saying so.

Nothing here touches `/etc/ocado-proxy/env`, so the token survives updates —
the routine keeps working without being reconfigured.

Confirm it came back up, using the same check as the deploy:

    systemctl is-active ocado-proxy
    TOKEN=$(sudo sed -n 's/^OCADO_PROXY_TOKEN=//p' /etc/ocado-proxy/env)
    curl -sSD- -o/dev/null http://127.0.0.1:8787/ocado/ocado-organic-carrots/627742011 \
        -H "Authorization: Bearer $TOKEN"

If that prints nothing at all the daemon is not listening — `-sS` keeps curl's
connection errors visible, where plain `-s` would swallow them and look like an
empty reply. `journalctl -u ocado-proxy -n 20` says why; a bad or missing
token in the environment file makes it exit at startup rather than serve
unauthenticated.

## Put TLS in front of it

The service binds `127.0.0.1` and speaks plain HTTP. The token is a bearer
credential — over clear HTTP anyone on the path can lift it and replay it — and
the response is HTML this repository parses for prices, so an on-path attacker
could rewrite the numbers. `update_prices.py` refuses a non-HTTPS
`PRICE_PROXY` unless it is localhost.

### Tailscale Funnel

The least work on a home connection: a permanent HTTPS hostname, certificates
handled for you, and no inbound port opened or domain required.

    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up

Enable HTTPS certificates for the tailnet once, under DNS in the admin console
(<https://login.tailscale.com/admin/dns>), and give the machine the `funnel`
node attribute in the tailnet policy file:

    "nodeAttrs": [
        {"target": ["autogroup:member"], "attr": ["funnel"]}
    ]

Then publish port 8787 and read back the hostname it was given:

    sudo tailscale funnel --bg 8787
    tailscale funnel status
    tailscale status --json | grep -m1 DNSName

That yields `https://<machine>.<tailnet>.ts.net`, which is what `PRICE_PROXY`
becomes. `--bg` keeps it serving across restarts. The proxy itself stays bound
to `127.0.0.1` — Funnel connects to it locally, so nothing new listens on the
LAN.

Funnel is genuinely public: anyone who has the URL can reach it, so the bearer
token remains the only thing standing between the internet and the service.
That is what it is for, but do not treat the hostname as a secret — it appears
in Certificate Transparency logs regardless.

To withdraw it: `sudo tailscale funnel --https=443 off`.

### Caddy

If the machine already has a domain pointed at it and an open port 443:

    prices.example.com {
        reverse_proxy 127.0.0.1:8787
    }

## Point the routine at it

In the routine's environment (<https://claude.ai/code>, the environment the
trigger uses):

    PRICE_PROXY=https://<machine>.<tailnet>.ts.net
    PRICE_PROXY_TOKEN=<the token from /etc/ocado-proxy/env>

and add that hostname to the environment's network allowlist, alongside
`www.trolley.co.uk`. `www.ocado.com` no longer needs to be allowed there —
nothing in the routine talks to it directly.

Check the whole path end to end from anywhere, which is what the routine will
be doing:

    curl -sSD- -o/dev/null https://<machine>.<tailnet>.ts.net/ocado/ocado-organic-carrots/627742011 \
        -H "Authorization: Bearer $TOKEN"

## Rotating the token

Rewrite `/etc/ocado-proxy/env`, `systemctl restart ocado-proxy`, then update
`PRICE_PROXY_TOKEN` in the environment. The routine runs weekly, so any
mismatch shows up as an empty Ocado column and 13 `FETCH FAILED … 401` lines
in the run output.
