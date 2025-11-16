from fastapi import APIRouter

router = APIRouter()


@router.get("/stream/{type}/{id}.json")
@router.get("/{encoded}/stream/{type}/{id}.json")
async def get_stream(
    encoded: str,
    type: str,
    id: str,
):
    """
    Stremio stream endpoint for movies and series.
    """

    return {
        "streams": [
            {
                "name": "Update Catalogs",
                "description": "Update the catalogs for the addon.",
                "url": f"https://watchly-eta.vercel.app/{encoded}/catalog/update/",
            }
        ]
    }
