class RPDBService:
    @staticmethod
    def get_poster_url(api_key: str, item_id: str) -> str:
        """
        Get poster URL for a specific item by IMDB ID.
        """
        return f"https://api.ratingposterdb.com/{api_key}/imdb/poster-default/{item_id}.jpg?fallback=true"
