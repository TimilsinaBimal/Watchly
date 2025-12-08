# Watchly
**Watchly** is a Stremio catalog addon that provides personalized movie and series recommendations based on your Stremio library. It uses The Movie Database (TMDB) API to generate intelligent recommendations from the content you've watched and loved.

## Features

- **Personalized Recommendations**: Analyzes your Stremio library to understand your viewing preferences.
- **Smart Filtering**: Automatically excludes content you've already watched.
- **Advanced Scoring**: Recommendations are intelligently weighted by recency and relevance.
- **Genre-Based Discovery**: Offers genre-specific catalogs based on your viewing history.
- **Similar Content**: Discover content similar to specific titles in your library.
- **Web Configuration**: Easy-to-use web interface for secure setup.
- **Secure Architecture**: Credentials are stored securely and never exposed in URLs.
- **Background Sync**: Keeps your catalogs updated automatically in the background.
- **Performance Optimized**: Intelligent caching for fast and reliable responses.

## Installation

### Using Docker (Recommended)

You can pull the latest image from the GitHub Container Registry.

1.  **Create a `docker-compose.yml` file:**

    ```yaml
    services:
      redis:
        image: redis:7-alpine
        container_name: watchly-redis
        restart: unless-stopped
        volumes:
          - redis_data:/data

      watchly:
        image: ghcr.io/timilsinabimal/watchly:latest
        container_name: watchly
        restart: unless-stopped
        ports:
          - "8000:8000"
        env_file:
          - .env
        depends_on:
          - redis

    volumes:
      redis_data:
    ```

2.  **Create a `.env` file:**

    ```env
    # Required
    TMDB_API_KEY=your_tmdb_api_key_here
    TOKEN_SALT=generate_a_random_secure_string_here

    # Optional
    PORT=8000
    REDIS_URL=redis://redis:6379/0
    ADDON_ID=com.bimal.watchly
    ADDON_NAME=Watchly
    TOKEN_TTL_SECONDS=0
    AUTO_UPDATE_CATALOGS=true
    ```

3.  **Start the application:**

    ```bash
    docker-compose up -d
    ```

4.  **Configure the addon:**
    Open `http://localhost:8000/configure` in your browser to set up your Stremio credentials and install the addon.

## Development

To run the project locally:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/TimilsinaBimal/Watchly.git
    cd Watchly
    ```

2.  **Install dependencies:**
    We recommend using [uv](https://github.com/astral-sh/uv) for fast dependency management.
    ```bash
    uv sync
    ```

3.  **Run the application:**
    ```bash
    uv run main.py --dev
    ```

## Contributing

We welcome contributions of all sizes!

- **Small Bug Fixes & Improvements**: Feel free to open a Pull Request directly.
- **Major Features & Refactors**: Please **open an issue first** to discuss your proposed changes. This helps ensure your work aligns with the project's direction and saves you time.

## Funding & Support

If you find Watchly useful, please consider supporting the project:
- [Buy me Mo:Mo](https://buymemomo.com/timilsinabimal)
- [Support on Ko-fi](https://ko-fi.com/I2I81OVJEH)
- [Donate via PayPal](https://www.paypal.com/donate/?hosted_button_id=KRQMVS34FC5KC)

## Bug Reports

Found a bug or have a feature request? Please [open an issue](https://github.com/TimilsinaBimal/Watchly/issues) on GitHub.

## Contributors

Thank you to everyone who has contributed to the project!

## Acknowledgements

Special thanks to **[The Movie Database (TMDB)](https://www.themoviedb.org/)** for providing the rich metadata that powers Watchly's recommendations.
