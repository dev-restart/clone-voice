from datetime import datetime

progress_events: dict[str, dict] = {}


def publish_progress(progress_id: str | None, percent: int, message: str, done: bool = False) -> None:
    if not progress_id:
        return
    progress_events[progress_id] = {"percent": percent, "message": message, "done": done, "timestamp": datetime.now().isoformat()}
