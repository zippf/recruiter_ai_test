from fastapi import HTTPException

from app.core.config import CALLBACK_SECRET


async def verify_callback_secret(authorization: str | None = None) -> str:
    """Require the shared bearer secret used by n8n callback routes."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Must be Bearer <token>",
        )
    token = authorization.split(" ")[1]
    if token != CALLBACK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid callback secret token")
    return token
