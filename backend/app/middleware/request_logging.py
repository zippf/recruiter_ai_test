import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        path = request.url.path
        method = request.method
        headers = dict(request.headers)
        auth_header = headers.get("authorization", "")
        has_auth = f"Yes ({auth_header[:25]}...)" if auth_header else "No"
        
        response = await call_next(request)
        process_time = time.time() - start_time
        
        with open("requests.log", "a") as f:
            f.write(f"[{method}] {path} | Auth: {has_auth} | Status: {response.status_code} | Time: {process_time:.4f}s\n")
            
        return response
