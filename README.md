[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I81OVJEH)
[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=KRQMVS34FC5KC)
# Watchly

**Watchly** is a Stremio catalog addon that provides personalized movie and series recommendations based on your Stremio library. It uses The Movie Database (TMDB) API to generate intelligent recommendations from the content you've watched and loved.

## What is Watchly?

Watchly is a FastAPI-based Stremio addon that:

- **Personalizes Recommendations**: Analyzes your Stremio library to understand your viewing preferences
- **Uses Your Loved Content**: Generates recommendations based on movies and series you've marked as "loved" in Stremio
- **Filters Watched Content**: Automatically excludes content you've already watched
- **Supports Movies & Series**: Provides recommendations for both movies and TV series
- **Genre-Based Discovery**: Offers genre-specific catalogs based on your viewing history
- **Similar Content**: Shows recommendations similar to specific titles when browsing

## What Does It Do?

1. **Connects to Your Stremio Library**: Securely authenticates with your Stremio account to access your library
2. **Analyzes Your Preferences**: Identifies your most loved movies and series as seed content
3. **Generates Recommendations**: Uses TMDB's recommendation engine to find similar content
4. **Filters & Scores**: Removes watched content and scores recommendations based on relevance
5. **Provides Stremio Catalogs**: Exposes catalogs that appear in your Stremio app for easy browsing

## Features

- ✅ **Personalized Recommendations** based on your Stremio library
- ✅ **Library-Based Filtering** - excludes content you've already watched
- ✅ **IMDB ID Support** - uses standard IMDB identifiers (Stremio standard)
- ✅ **Movies & Series Support** - recommendations for both content types
- ✅ **Genre-Based Catalogs** - dynamic genre catalogs based on your preferences
- ✅ **Similar Content Discovery** - find content similar to specific titles
- ✅ **Web Configuration Interface** - easy setup through a web UI
- ✅ **Caching** - optimized performance with intelligent caching
- ✅ **Docker Support** - easy deployment with Docker and Docker Compose

## Installation

### Prerequisites

- Python 3.10 or higher
- TMDB API key ([Get one here](https://www.themoviedb.org/settings/api))
- Stremio account credentials (username/email and password)

### Option 1: Docker Installation (Recommended)

#### Using Docker Compose

1. **Clone the repository:**
   ```bash
   git clone https://github.com/TimilsinaBimal/Watchly.git
   cd Watchly
   ```

2. **Create a `.env` file:**
   ```bash
   cp .env.example .env
   # Edit .env and add your credentials
   ```

3. **Edit `.env` file with your credentials:**
   ```
   TMDB_API_KEY=your_tmdb_api_key_here
   PORT=8000
   ADDON_ID=com.bimal.watchly
   ```

4. **Start the application:**
   ```bash
   docker-compose up -d
   ```

5. **Access the application:**
   - API: `http://localhost:8000`
   - Configuration page: `http://localhost:8000/configure`
   - API Documentation: `http://localhost:8000/docs`

#### Using Docker Only

1. **Build the image:**
   ```bash
   docker build -t watchly .
   ```

2. **Run the container:**
   ```bash
   docker run -d \
     --name watchly \
     -p 8000:8000 \
     -e TMDB_API_KEY=your_tmdb_api_key_here \
     -e PORT=8000 \
     -e ADDON_ID=com.bimal.watchly \
     watchly
   ```

### Option 2: Manual Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/TimilsinaBimal/Watchly.git
   cd Watchly
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set environment variables:**
   
   Create a `.env` file in the project root:
   ```
   TMDB_API_KEY=your_tmdb_api_key_here
   PORT=8000
   ADDON_ID=com.bimal.watchly
   ```
   
   Or export them in your shell:
   ```bash
   export TMDB_API_KEY=your_tmdb_api_key_here
   export PORT=8000
   export ADDON_ID=com.bimal.watchly
   ```

5. **Run the application:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

   Or using Python directly:
   ```bash
   python main.py
   ```

6. **Access the application:**
   - API: `http://localhost:8000`
   - Configuration page: `http://localhost:8000/configure`
   - API Documentation: `http://localhost:8000/docs`

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `TMDB_API_KEY` | Your TMDB API key | Yes | - |
| `PORT` | Server port | No | 8000 |
| `ADDON_ID` | Stremio addon identifier | No | com.bimal.watchly |

### User Configuration

Users configure their Stremio credentials through the web interface at `/configure`. Credentials are:
- Encoded in the addon URL (base64)
- Never stored on the server
- Used only for API requests to Stremio

## How It Works

1. **User Configuration**: User enters Stremio credentials via web interface
2. **Credential Encoding**: Credentials are base64 encoded and included in the addon URL
3. **Library Fetching**: When catalog is requested, service authenticates with Stremio and fetches user's library
4. **Seed Selection**: Uses most recent "loved" items (default: 10) as seed content
5. **Recommendation Generation**: For each seed, fetches recommendations from TMDB
6. **Filtering**: Removes items already in user's watched library
7. **Deduplication**: Combines recommendations from multiple seeds, scoring by relevance
8. **Metadata Fetching**: Fetches full metadata from TMDB addon
9. **Response**: Returns formatted catalog items compatible with Stremio

## Project Structure

```
Watchly/
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── main.py              # API router
│   │   └── endpoints/
│   │       ├── manifest.py      # Stremio manifest endpoint
│   │       ├── catalogs.py      # Catalog endpoints
│   │       ├── streams.py       # Stream endpoints
│   │       └── caching.py       # Cache management
│   ├── config.py                # Application settings
│   ├── models.py                # Pydantic models
│   ├── services/
│   │   ├── tmdb_service.py      # TMDB API integration
│   │   ├── stremio_service.py   # Stremio API integration
│   │   ├── recommendation_service.py  # Recommendation engine
│   │   └── catalog.py           # Dynamic catalog service
│   └── utils.py                 # Utility functions
├── static/
│   ├── index.html              # Configuration page
│   ├── style.css               # Styling
│   ├── script.js               # Configuration logic
│   └── logo.png                # Addon logo
├── main.py                      # FastAPI application entry point
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker image definition
├── docker-compose.yml           # Docker Compose configuration
└── README.md                    # This file
```

## Development

### Running in Development Mode

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Testing

```bash
# Test manifest endpoint
curl http://localhost:8000/manifest.json

# Test catalog endpoint (requires encoded credentials)
curl http://localhost:8000/{encoded}/catalog/movie/watchly.rec.json
```

## Security Notes

- **Credentials in URL**: User credentials are base64 encoded in the addon URL. While encoded, they are not encrypted. Users should be aware of this.
- **HTTPS Recommended**: Always use HTTPS in production to protect credentials in transit.
- **Environment Variables**: Never commit `.env` files or expose API keys in code.

## Troubleshooting

### No recommendations appearing

- Ensure user has "loved" items in their Stremio library
- Check that TMDB API key has proper permissions
- Review application logs for errors

## License

See [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on GitHub.
