from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/stream/{type}/{id}.json")
@router.get("/{token}/stream/{type}/{id}.json")
async def get_stream(
    token: str | None,
    type: str,
    id: str,
    request: Request,
):
    """
    Stremio stream endpoint for movies and series.
    """

    base_url = str(request.base_url).rstrip("/")
    update_path = f"/{token}/catalog/update/" if token else "/configure"

    return {
        "streams": [
            {
                "name": "Update Catalogs",
                "description": "Update the catalogs for the addon.",
                "url": f"{base_url}{update_path}",
            }
        ]
    }
