"""FastAPI application entry point for OpenSource Guardian."""

from fastapi import FastAPI
from src.guardian import __version__
from src.guardian.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory for OpenSource Guardian."""
    current_settings = settings or get_settings()

    app = FastAPI(
        title=current_settings.app_name,
        version=__version__,
        description="Switch-powered AI teammate for open-source communities",
    )

    @app.get("/health", tags=["System"])
    async def health_check() -> dict[str, str]:
        """Simple health check endpoint returning service liveness status."""
        return {
            "status": "healthy",
            "app": current_settings.app_name,
            "version": __version__,
            "environment": current_settings.environment,
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.guardian.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=(settings.environment == "development"),
    )
