from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging


correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")
user_email_ctx: ContextVar[str] = ContextVar("user_email", default="anonymous")


class JSONLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": correlation_id_ctx.get(),
            "user_email": user_email_ctx.get(),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_object)


logger = logging.getLogger("backend")
logger.setLevel(logging.INFO)
for handler in logger.handlers[:]:
    logger.removeHandler(handler)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(JSONLogFormatter())
logger.addHandler(stream_handler)
