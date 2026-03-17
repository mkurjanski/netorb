import logging


class DBLogHandler(logging.Handler):
    """Logging handler that persists records to TaskLog for live streaming."""

    def __init__(self, job_id: str, device=None):
        super().__init__()
        self.job_id = job_id
        self.device = device

    def emit(self, record: logging.LogRecord) -> None:
        # Import here to avoid loading models before Django is ready.
        from .models import TaskLog

        level = record.levelname if record.levelname in TaskLog.Level.values else "INFO"
        try:
            TaskLog.objects.create(
                job_id=self.job_id,
                device=self.device,
                level=level,
                message=self.format(record),
            )
        except Exception:
            self.handleError(record)
