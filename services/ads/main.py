"""FM21 ads service — transcode, DB, injector enqueue (U24)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.ads.routes import router
from services.injector.fanout import load_active_cities

CITIES_YAML_PATH = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.active_cities = load_active_cities(CITIES_YAML_PATH)
    yield


app = FastAPI(title="FM21 Ads", lifespan=lifespan)
app.include_router(router)
