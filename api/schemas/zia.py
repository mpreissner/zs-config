from typing import List

from pydantic import BaseModel


class UrlLookupRequest(BaseModel):
    """Request body for the URL lookup endpoint."""
    urls: List[str]
