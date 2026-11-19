import hmac

from fastapi import Header, HTTPException

from .config import settings


def require_processor_secret(x_processor_secret: str = Header(default="")) -> None:
    """Reject calls that do not carry the shared worker secret.

    The secret is only known to the Vercel API layer; it never reaches a browser.
    """
    if not hmac.compare_digest(x_processor_secret, settings.processor_secret):
        raise HTTPException(status_code=401, detail="Invalid processor secret.")
