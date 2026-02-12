from fastapi import FastAPI

from app.api.financial_report_api import router as financial_report_router
from app.api.health_api import router as health_router
from app.api.industry_api import router as industry_router
from app.api.macro_api import router as macro_router
from app.api.market_api import router as market_router
from app.api.page_api import router as page_router


def register_routers(app: FastAPI) -> None:
    """Attach all route modules to the FastAPI application."""
    app.include_router(page_router)
    app.include_router(market_router)
    app.include_router(macro_router)
    app.include_router(industry_router)
    app.include_router(financial_report_router)
    app.include_router(health_router)
