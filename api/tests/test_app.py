"""The app's lifespan: it builds what the routes read from app.state, and disposes the engine."""

import pytest
from nursing_api.app import create_app
from nursing_api.settings import Settings
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_lifespan_disposes_the_engine(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    disposed: list[AsyncEngine] = []
    real_dispose = AsyncEngine.dispose

    async def spy(self: AsyncEngine, close: bool = True) -> None:
        disposed.append(self)
        await real_dispose(self, close=close)

    monkeypatch.setattr(AsyncEngine, "dispose", spy)
    app = create_app(Settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        assert disposed == []
    assert disposed == [engine]
