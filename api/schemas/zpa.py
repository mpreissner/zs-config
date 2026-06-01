from typing import Optional

from pydantic import BaseModel


class CertificateRotateRequest(BaseModel):
    """Request body for the certificate rotation endpoint."""
    domain: str
    cert_path: str
    key_path: str


class ApplicationEnabledPatch(BaseModel):
    enabled: bool


class ConnectorEnabledPatch(BaseModel):
    enabled: bool


class ConnectorNamePatch(BaseModel):
    name: str


class ConnectorGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ConnectorGroupEnabledPatch(BaseModel):
    enabled: bool


class ServiceEdgeEnabledPatch(BaseModel):
    enabled: bool


class PRAPortalCreate(BaseModel):
    name: str
    domain: str
    certificate_id: str
    enabled: bool = True
    description: Optional[str] = None
    user_notification_enabled: bool = False
    user_notification: Optional[str] = None


class PRAPortalEnabledPatch(BaseModel):
    enabled: bool


class PRAConsoleEnabledPatch(BaseModel):
    enabled: bool
