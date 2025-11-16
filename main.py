from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware
from app.api.main import api_router
from app.config import settings

app = FastAPI(
    title="Watchly",
    description="Stremio catalog addon for movie and series recommendations",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
