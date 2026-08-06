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
    curl -sD- -o/dev/null http://127.0.0.1:8787/ocado/ocado-organic-carrots/627742011 \
        -H "Authorization: Bearer $TOKEN"

`HTTP/1.0 200 OK` means it works. `401` means the token did not match, `502`
means Ocado refused this machine too — check `journalctl -u ocado-proxy` for
the upstream status.

## Put TLS in front of it

The service binds `127.0.0.1` and speaks plain HTTP. The token is a bearer
credential — over clear HTTP anyone on the path can lift it and replay it, so
it must not reach the internet unencrypted. `update_prices.py` refuses a
non-HTTPS `PRICE_PROXY` unless it is localhost.

Caddy, which gets a certificate on its own:

    prices.example.com {
        reverse_proxy 127.0.0.1:8787
    }

A Cloudflare Tunnel works too and needs no open inbound port, which is the
better choice on a home connection:

    cloudflared tunnel --url http://127.0.0.1:8787

## Point the routine at it

In the routine's environment (<https://claude.ai/code>, the environment the
trigger uses):

    PRICE_PROXY=https://prices.example.com
    PRICE_PROXY_TOKEN=<the token from /etc/ocado-proxy/env>

and add that hostname to the environment's network allowlist, alongside
`www.trolley.co.uk`. `www.ocado.com` no longer needs to be allowed there —
nothing in the routine talks to it directly.

## Rotating the token

Rewrite `/etc/ocado-proxy/env`, `systemctl restart ocado-proxy`, then update
`PRICE_PROXY_TOKEN` in the environment. The routine runs weekly, so any
mismatch shows up as an empty Ocado column and 13 `FETCH FAILED … 401` lines
in the run output.
