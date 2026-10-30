"""Remove distrusted roots from the image trust store and rebuild it.

Runs at image build, after the host's trust store has been copied in. The host
export can carry roots the base image has already dropped, so filtering by
fingerprint here is what keeps them out, whatever the host or base image holds.
The build fails if a distrusted root survives.
"""

import hashlib
import json
import pathlib
import re
import ssl
import subprocess
import sys

# SHA-256 of the DER certificate, shared with distrust_cas_node.js. Covers the
# October 2026 eMudhra key compromise, plus the Comodo root Debian removed for it.
DISTRUSTED = json.loads(
    pathlib.Path(__file__).with_name("distrusted_cas.json").read_text()
)

SOURCE_DIRS = ("/usr/share/ca-certificates", "/usr/local/share/ca-certificates")
SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL
)


def fingerprint(pem: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def filter_file(path: pathlib.Path) -> None:
    blocks = PEM_BLOCK.findall(path.read_text(errors="ignore"))
    kept = [block for block in blocks if fingerprint(block) not in DISTRUSTED]
    if len(kept) == len(blocks):
        return
    for block in blocks:
        name = DISTRUSTED.get(fingerprint(block))
        if name:
            print(f"Removing {name} from {path}")
    if kept:
        path.write_text("\n".join(kept) + "\n")
    else:
        path.unlink()


def main() -> int:
    for source_dir in SOURCE_DIRS:
        for path in pathlib.Path(source_dir).rglob("*.crt"):
            filter_file(path)

    # --fresh also clears the hashed links in /etc/ssl/certs, which OpenSSL reads
    # alongside the bundle.
    subprocess.run(["update-ca-certificates", "--fresh"], check=True)

    bundle = pathlib.Path(SYSTEM_BUNDLE).read_text(errors="ignore")
    found = [
        DISTRUSTED[fingerprint(block)]
        for block in PEM_BLOCK.findall(bundle)
        if fingerprint(block) in DISTRUSTED
    ]
    if found:
        print(f"Distrusted roots still in {SYSTEM_BUNDLE}: {found}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
