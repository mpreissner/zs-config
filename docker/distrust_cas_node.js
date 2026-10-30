// Build the frontend stage's trust store without distrusted roots.
//
// Merges the host's trust store into the base image's bundle, filters both by
// fingerprint, and fails the build if Node can still see a distrusted root.

const crypto = require("crypto");
const fs = require("fs");
const tls = require("tls");

const DISTRUSTED = require("./distrusted_cas.json");

const HOST_BUNDLE = "/tmp/ca-bundle.pem";
const SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt";

const PEM_BLOCK = /-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g;

// SHA-256 of the DER certificate.
function fingerprint(pem) {
  const body = pem.replace(/-----[^-]+-----|\s/g, "");
  return crypto.createHash("sha256").update(Buffer.from(body, "base64")).digest("hex");
}

const kept = new Map();
for (const path of [SYSTEM_BUNDLE, HOST_BUNDLE]) {
  for (const pem of fs.readFileSync(path, "utf8").match(PEM_BLOCK) ?? []) {
    const fp = fingerprint(pem);
    if (fp in DISTRUSTED) {
      console.log(`Removing ${DISTRUSTED[fp]} from ${path}`);
    } else {
      kept.set(fp, pem);
    }
  }
}
fs.writeFileSync(SYSTEM_BUNDLE, [...kept.values()].join("\n") + "\n");

const found = tls.getCACertificates("default")
  .map(fingerprint)
  .filter((fp) => fp in DISTRUSTED)
  .map((fp) => DISTRUSTED[fp]);
if (found.length > 0) {
  console.error(`Distrusted roots still visible to Node: ${found.join(", ")}`);
  process.exit(1);
}
