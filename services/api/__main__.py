"""python -m services.api"""

from __future__ import annotations

import uvicorn

from services.api.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "services.api.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
    )


if __name__ == "__main__":
    main()
