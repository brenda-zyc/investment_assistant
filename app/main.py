from fastapi import FastAPI

from app.api import register_routers
from app.db import init_db


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(title="A-share Investment Analysis")

    @application.on_event("startup")
    def on_startup() -> None:
        """Initialize local storage on service startup."""
        init_db()

    register_routers(application)
    # TODO: Add environment-driven FastAPI settings (docs URL, trusted hosts, CORS policy).
    return application


app = create_app()

# Re-export route handlers for backward compatibility with local scripts.
from app.api.financial_report_api import (  # noqa: E402,F401
    FinancialReportUrlRequest,
    LlmSessionConfigRequest,
    financial_report_analysis,
    financial_report_autoread,
    financial_report_url_analysis,
    llm_session_config_save,
    llm_session_config_status,
    llm_test_connection,
)
from app.api.industry_api import industry_cycles  # noqa: E402,F401
from app.api.macro_api import macro_indicators, macro_signals  # noqa: E402,F401
from app.api.market_api import (  # noqa: E402,F401
    AnalyzeRequest,
    MultiAnalyzeRequest,
    analyze,
    analyze_multi,
    realtime_prices,
    stock_metrics,
)
from app.api.page_api import index  # noqa: E402,F401
