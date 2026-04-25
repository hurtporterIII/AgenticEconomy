from __future__ import annotations

from fastapi import APIRouter

from api.routes.population_spawn import population_router
from api.routes.economy_tx import economy_tx_router
from api.routes.routes_map import routes_map_router
from api.routes.bridge import bridge_router
from api.routes.legacy import legacy_router

router = APIRouter(prefix="/api", tags=["demo"])
router.include_router(population_router)
router.include_router(economy_tx_router)
router.include_router(routes_map_router)
router.include_router(bridge_router)
router.include_router(legacy_router)
