from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Simple liveness endpoint."""
    return {"status": "ok"}
