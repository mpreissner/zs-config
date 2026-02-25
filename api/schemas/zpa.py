from pydantic import BaseModel


class CertificateRotateRequest(BaseModel):
    """Request body for the certificate rotation endpoint."""
    domain: str
    cert_path: str
    key_path: str
