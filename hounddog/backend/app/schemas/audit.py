from datetime import datetime
from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: str
    timestamp: datetime
    user_email: str
    user_sub: str
    action: str
    resource_type: str
    resource_id: str | None
    endpoint: str
    summary: str
    request_body: dict | None = None
    response_status: int
    ip_address: str | None = None
    changes: dict | None = None

    model_config = {"from_attributes": True}


class AuditLogList(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
