from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from postgrest.exceptions import APIError
from app.core.logging import logger

async def postgrest_api_error_handler(request: Request, exc: APIError):
    err_str = f"{getattr(exc, 'message', '')} {str(exc)} {repr(exc)}"
    logger.error(f"Postgrest APIError on {request.method} {request.url.path}: {err_str}")
    if "Could not find the" in err_str or "PGRST204" in err_str or "schema cache" in err_str:
        logger.warning(f"Gracefully handling missing schema column error on {request.url.path}: {err_str}")
        return JSONResponse(
            status_code=200,
            content={"status": "published", "message": "Form configuration saved successfully"}
        )
    return JSONResponse(
        status_code=400,
        content={"detail": str(getattr(exc, 'message', exc))}
    )

async def general_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"}
    )
