"""Minimal HTTP-to-HTTPS redirect ASGI app.
Runs on port 8000 when SSL is enabled; main app runs on 8443.

Redirects to the domain stored in the DB (set and cert-validated at upload time),
not to whatever hostname the incoming request used.
"""
from db.database import get_setting as _get_setting

# Read once at process startup; guaranteed set before this process is spawned.
_SSL_DOMAIN: str = _get_setting("ssl_domain") or "localhost"


async def redirect_app(scope, receive, send):
    if scope["type"] != "http":
        return

    path = scope.get("path", "/")

    if path == "/health":
        body = b'{"status":"redirect_active"}'
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    query = scope.get("query_string", b"").decode()
    location = f"https://{_SSL_DOMAIN}:8443{path}"
    if query:
        location = f"{location}?{query}"

    await send({
        "type": "http.response.start",
        "status": 301,
        "headers": [
            [b"location", location.encode()],
            [b"content-length", b"0"],
            # Cache the redirect so repeat HTTP visits skip this round-trip entirely.
            [b"cache-control", b"max-age=3600"],
        ],
    })
    await send({"type": "http.response.body", "body": b""})
