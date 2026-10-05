import httpx

from app.core.logging import logger


async def dispatch_n8n_webhook(url: str, payload: dict, context_label: str) -> bool:
    if not url:
        logger.error(f"Cannot dispatch webhook for {context_label}: URL not configured")
        return False
    logger.info(f"Dispatching outbound webhook to {url} for {context_label}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=180.0)
            if response.status_code in (200, 201, 202, 204):
                logger.info(
                    f"Successfully dispatched webhook for {context_label} (status: {response.status_code})"
                )
                return True
            logger.error(
                f"Failed to dispatch webhook for {context_label} "
                f"(status: {response.status_code}, response: {response.text})"
            )
            return False
    except Exception as exc:
        logger.error(f"Exception during webhook dispatch for {context_label}: {exc}")
        return False
