from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReportFilters:
    from_time: datetime
    to_time: datetime
    course_id: int | None = None
    class_name: str | None = None
    source: str | None = None
    session_id: int | None = None
    bucket: str = 'day'
    data_scope: str = 'ALL'
