"""Remove distrusted roots from the image trust store and rebuild it.

Runs at image build, after the host's trust store has been copied in. The host
export can carry roots the base image has already dropped, so filtering by
fingerprint here is what keeps them out, whatever the host or base image holds.
The build fails if a distrusted root survives.
"""

import hashlib
import pathlib
import re
import ssl
import subprocess
import sys

# SHA-256 of the DER certificate.
DISTRUSTED = {
    # eMudhra key compromise, October 2026.
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b": "emSign ECC Root CA - G3",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3": "emSign ECC Root CA - C3",
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f": "emSign Root CA - C1",
    # Removed by Debian's fix for the same incident.
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4": "Comodo AAA Services root",
}

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
