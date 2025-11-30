import os

import uvicorn

from app.core.app import app  # noqa: F401
from app.core.config import settings

if __name__ == "__main__" and settings.APP_ENV != "vercel":
    PORT = os.getenv("PORT", settings.PORT)
    reload = settings.APP_ENV == "development"
    uvicorn.run("app.core.app:app", host="0.0.0.0", port=int(PORT), reload=reload)
