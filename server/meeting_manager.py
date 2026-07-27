"""In-memory meeting room storage."""

import secrets
import string
import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


def _generate_id(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Meeting:
    def __init__(self, meeting_id: str, host: str):
        self.meeting_id = meeting_id
        self.host = host
        self.participants: dict[str, str] = {host: host}  # username -> username
        self.created_at = time.time()

    def add(self, username: str) -> bool:
        if username in self.participants:
            return False
        self.participants[username] = username
        return True

    def remove(self, username: str):
        self.participants.pop(username, None)

    def is_empty(self) -> bool:
        return len(self.participants) == 0

    def usernames(self) -> list[str]:
        return list(self.participants.keys())


class MeetingManager:
    def __init__(self):
        self._meetings: dict[str, Meeting] = {}
        self._lock = Lock()

    def create(self, host: str) -> Meeting:
        mid = _generate_id()
        meeting = Meeting(mid, host)
        with self._lock:
            self._meetings[mid] = meeting
        logger.info("Meeting %s created by %s", mid, host)
        return meeting

    def get(self, meeting_id: str) -> Meeting | None:
        with self._lock:
            return self._meetings.get(meeting_id)

    def remove_if_empty(self, meeting_id: str):
        with self._lock:
            m = self._meetings.get(meeting_id)
            if m and m.is_empty():
                del self._meetings[meeting_id]
                logger.info("Meeting %s removed (empty)", meeting_id)


meetings = MeetingManager()
