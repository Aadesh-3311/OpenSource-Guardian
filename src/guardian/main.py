"""FastAPI application entry point for OpenSource Guardian."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncGenerator

from fastapi import FastAPI
from src.guardian import __version__
from src.guardian.adapters.github_client import GitHubClient
from src.guardian.adapters.switch_client import SwitchRestClient, SwitchWebSocketClient
from src.guardian.adapters.switch_dispatcher import SwitchEventDispatcher
from src.guardian.config import Settings, get_settings

logger = logging.getLogger("guardian.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory for OpenSource Guardian with managed lifespan."""
    current_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage startup and shutdown lifecycles for OpenSource Guardian."""
        has_agent_id = bool(current_settings.switch_agent_id)
        has_api_key = bool(
            current_settings.switch_api_key
            and current_settings.switch_api_key.get_secret_value()
        )

        ws_task: asyncio.Task[None] | None = None
        ws_client: SwitchWebSocketClient | None = None
        github_client: GitHubClient | None = None
        switch_rest_client: SwitchRestClient | None = None

        if has_agent_id and has_api_key:
            logger.info(
                "Switch credentials configured (agent_id: %s). Initializing Switch listener...",
                current_settings.switch_agent_id,
            )
            try:
                github_client = GitHubClient(
                    base_url=current_settings.github_api_base_url,
                    token=current_settings.github_token,
                )
                switch_rest_client = SwitchRestClient(
                    base_url=current_settings.switch_api_url,
                    agent_id=current_settings.switch_agent_id,
                    api_key=current_settings.switch_api_key,
                )
                dispatcher = SwitchEventDispatcher(
                    switch_client=switch_rest_client,
                    github_client=github_client,
                    default_repo=current_settings.default_repo,
                )
                ws_client = SwitchWebSocketClient(
                    base_url=current_settings.switch_api_url,
                    agent_id=current_settings.switch_agent_id,
                    api_key=current_settings.switch_api_key,
                    rooms=current_settings.switch_rooms,
                    connection_id=current_settings.switch_connection_id,
                    on_event=dispatcher.dispatch_event,
                )

                app.state.ws_client = ws_client
                app.state.switch_dispatcher = dispatcher
                app.state.github_client = github_client
                app.state.switch_rest_client = switch_rest_client

                ws_task = asyncio.create_task(
                    ws_client.run_loop(),
                    name="switch_websocket_listener",
                )
                app.state.ws_task = ws_task
                logger.info("Switch WebSocket listener background task started successfully.")
            except Exception as err:
                logger.error("Failed to start Switch WebSocket listener: %s", err, exc_info=True)
                if switch_rest_client:
                    await switch_rest_client.close()
                if github_client:
                    await github_client.aclose()
                raise
        else:
            logger.info(
                "Switch credentials not fully configured (agent_id: %s, api_key: %s). "
                "Running in health-only mode without active Switch connection.",
                "provided" if has_agent_id else "missing",
                "provided" if has_api_key else "missing",
            )
            app.state.ws_client = None
            app.state.ws_task = None
            app.state.switch_dispatcher = None
            app.state.github_client = None
            app.state.switch_rest_client = None

        yield

        # Graceful shutdown
        logger.info("Initiating OpenSource Guardian shutdown...")
        if ws_client is not None:
            ws_client.stop()
        if ws_task is not None and not ws_task.done():
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
            except Exception as err:
                logger.error("Error awaiting WebSocket listener cancellation: %s", err, exc_info=True)

        if switch_rest_client is not None:
            await switch_rest_client.close()
        if github_client is not None:
            await github_client.aclose()

        logger.info("OpenSource Guardian shutdown completed.")

    app = FastAPI(
        title=current_settings.app_name,
        version=__version__,
        description="Switch-powered AI teammate for open-source communities",
        lifespan=lifespan,
    )
    app.state.settings = current_settings

    @app.get("/health", tags=["System"])
    async def health_check() -> dict[str, str]:
        """Simple health check endpoint returning service liveness status."""
        mode = "agent" if getattr(app.state, "ws_task", None) is not None else "health_only"
        return {
            "status": "healthy",
            "app": current_settings.app_name,
            "version": __version__,
            "environment": current_settings.environment,
            "mode": mode,
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    port = int(os.environ.get("PORT", str(settings.port)))
    uvicorn.run(
        "src.guardian.main:app",
        host=settings.host,
        port=port,
        log_level=settings.log_level.lower(),
        reload=(settings.environment == "development"),
    )
