"""Launch uvicorn with an explicit SSL context enforcing TLS 1.2+."""
import asyncio
import os
import ssl
import sys

# Script lives inside api/, but must import from the project root (/app).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn


def main() -> None:
    cert, key = sys.argv[1], sys.argv[2]
    config = uvicorn.Config(
        "api.main:app",
        host="0.0.0.0",
        port=8443,
        ssl_certfile=cert,
        ssl_keyfile=key,
    )
    config.load()
    config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
