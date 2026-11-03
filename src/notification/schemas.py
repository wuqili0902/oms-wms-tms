from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    type: str
    channel: str
    title: str
    body: str
    data: str | None = None
    is_read: bool
    created_at: str | None = None


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    total: int
    page: int
    page_size: int


class MessageResponse(BaseModel):
    message: str


class NotificationPreferenceItem(BaseModel):
    id: int
    notification_type: str
    channel: str
    enabled: bool


class NotificationPreferenceInput(BaseModel):
    notification_type: str
    channel: str
    enabled: bool = True


class NotificationPreferenceResponse(BaseModel):
    preferences: list[NotificationPreferenceItem]
