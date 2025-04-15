from typing import Dict, List, Optional

from pydantic import AnyHttpUrl, BaseModel


class JenkinsBuild(BaseModel):
    number: int
    result: Optional[str]
    actions: List[Dict]


class DumpArguments(BaseModel):
    url: AnyHttpUrl
    use_alt_dumper: bool
    add_blacklist: bool
    use_privdump: bool
    initial_message_id: Optional[int] = None


class PendingReview(BaseModel):
    request_id: str
    original_chat_id: int
    original_message_id: int
    requester_id: int
    requester_username: Optional[str]
    url: AnyHttpUrl
    review_chat_id: int
    review_message_id: int


class AcceptOptionsState(BaseModel):
    alt: bool = False
    force: bool = False
    blacklist: bool = False
    privdump: bool = False