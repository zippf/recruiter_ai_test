import time
import json
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.logging import logger, correlation_id_ctx, user_email_ctx

NOISY_PATHS = {"/docs", "/openapi.json", "/", "/health"}

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        corr_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        user_email = request.headers.get("x-user-email") or "anonymous"

        token_corr = correlation_id_ctx.set(corr_id)
        token_user = user_email_ctx.set(user_email)

        start_time = time.time()
        try:
            response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # Suppress log noise for OPTIONS preflight, docs, and health checks
            is_noisy = request.method == "OPTIONS" or request.url.path in NOISY_PATHS
            if not is_noisy:
                logger.info(json.dumps({
                    "event": "http_request_complete",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms
                }))
            
            response.headers["X-Correlation-ID"] = corr_id
            return response
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(json.dumps({
                "event": "http_request_error",
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
                "error_detail": str(exc)
            }), exc_info=True)
            raise exc
        finally:
            correlation_id_ctx.reset(token_corr)
            user_email_ctx.reset(token_user)
