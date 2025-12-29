# Caten API

A FastAPI-based backend server for text and image processing with LLM integration. The API provides endpoints for extracting text from images, analyzing important words, and generating contextual explanations.

## Features

- **Image to Text**: Extract readable text from images using GPT-4 Turbo with Vision
- **PDF to Text**: Extract readable text from PDF files and return in markdown format
- **Important Words Analysis**: Identify the most important/difficult words in text
- **Word Explanations**: Get contextual meanings and examples with SSE streaming
- **Additional Examples**: Generate more simplified examples for words
- **Rate Limiting**: Configurable rate limiting with Redis
- **Monitoring**: Prometheus metrics and structured logging
- **Production Ready**: Docker support, health checks, and proper error handling

## API Endpoints

### 1. Extract Text from Image
- **POST** `/api/v1/image-to-text`
- Upload an image file (JPEG, JPG, PNG, HEIC) to extract text
- Maximum file size: 5MB
- Handles rotated/tilted images and transparent overlays

### 2. Extract Text from PDF
- **POST** `/api/v1/pdf-to-text`
- Upload a PDF file to extract text in markdown format
- Maximum file size: 2MB
- Supports multi-page PDFs with proper formatting
- Returns structured markdown content

### 3. Get Important Words
- **POST** `/api/v1/important-words-from-text`
- Analyze text to find the top 10 most important/difficult words
- Returns word positions in the original text

### 4. Get Word Explanations (Streaming)
- **POST** `/api/v1/words-explanation`
- Stream contextual meanings and examples via Server-Sent Events
- Concurrent processing for multiple words

### 5. Get More Examples
- **POST** `/api/v1/get-more-explanations`
- Generate additional simplified example sentences for a word

## Quick Start

### Prerequisites

- Python 3.9+
- OpenAI API key
- Redis (for rate limiting)
- Tesseract OCR (for image processing)
- PyPDF2 and pdfplumber (for PDF processing)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd caten
```

2. Copy environment configuration:
```bash
cp environment.example .env
```

3. Edit `.env` file with your configuration:
```bash
OPENAI_API_KEY=your_openai_api_key_here
```

4. Run the application:
```bash
./start.sh
```

The API will be available at `http://localhost:8000`

### Using Docker

1. Set up environment:
```bash
cp environment.example .env
# Edit .env with your configuration
```

2. Run with Docker Compose:
```bash
docker-compose up -d
```

This will start:
- Caten API server on port 8000
- Redis on port 6379
- Prometheus on port 9090
- Grafana on port 3000 (admin/admin)

## Configuration

All configuration is managed through environment variables or the `.env` file:

### Required Settings
- `OPENAI_API_KEY`: Your OpenAI API key

### Optional Settings
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `DEBUG`: Enable debug mode (default: False)
- `LOG_LEVEL`: Logging level (default: INFO)
- `ENABLE_RATE_LIMITING`: Enable rate limiting (default: True)
- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Rate limit per minute (default: 60)
- `REDIS_URL`: Redis connection URL (default: redis://localhost:6379)
- `MAX_FILE_SIZE_MB`: Maximum file size in MB (default: 5)
- `ALLOWED_IMAGE_TYPES`: Allowed image types (default: jpeg,jpg,png,heic)

## Development

### Running Tests

```bash
# Install development dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/ -v
```

### Database migrations

For local development, the MariaDB schema is defined in `app/database/schema.sql` and applied on first setup.
If you are upgrading an existing database, you may need to run manual `ALTER TABLE` statements.

For example, to add the `contextual_meaning` column used by the saved words APIs:

```sql
ALTER TABLE saved_word
ADD COLUMN contextual_meaning VARCHAR(1000) NULL;
```

### Code Quality

```bash
# Format code
black app/ tests/

# Lint code
flake8 app/ tests/

# Type checking
mypy app/
```

### API Documentation

When running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Monitoring

### Health Check
- `GET /health`: Service health status

### Metrics
- `GET /metrics`: Prometheus metrics (if enabled)

### Logs
Structured JSON logs are written to stdout and can be collected by your logging infrastructure.

## Error Handling

All APIs return standardized error responses:

```json
{
  "error_code": "ERROR_CODE",
  "error_message": "Human readable error message"
}
```

Common error codes:
- `VAL_001`: Validation error
- `FILE_001`: File validation error
- `IMG_001`: Image processing error
- `LLM_001`: LLM service error
- `RATE_001`: Rate limit exceeded

## Architecture

```
app/
├── main.py              # FastAPI application
├── config.py            # Configuration management
├── exceptions.py        # Custom exceptions and handlers
├── models.py           # Pydantic models
├── routes/             # API routes
│   ├── api.py          # Main API endpoints
│   └── health.py       # Health check endpoints
└── services/           # Business logic services
    ├── image_service.py    # Image processing
    ├── text_service.py     # Text analysis
    ├── rate_limiter.py     # Rate limiting
    └── llm/               # LLM services
        └── open_ai.py      # OpenAI integration
```

## Production Deployment

### Docker Production Setup

1. Build production image:
```bash
docker build -t caten-api .
```

2. Run with production settings:
```bash
docker run -d \
  --name caten-api \
  -p 8000:8000 \
  -e OPENAI_API_KEY=your_key \
  -e DEBUG=false \
  -e LOG_LEVEL=WARNING \
  caten-api
```

### Kubernetes Deployment

Example deployment configuration is available in the `k8s/` directory (if provided).

### Environment Considerations

- Set `DEBUG=false` in production
- Use `LOG_LEVEL=WARNING` or `ERROR` in production
- Configure proper rate limiting based on your needs
- Set up monitoring and alerting for the `/health` endpoint
- Use a proper Redis instance for rate limiting
- Configure CORS appropriately for your frontend domains

## Security

- All endpoints are currently unauthenticated but designed for easy auth integration
- File uploads are validated for type and size
- Rate limiting prevents abuse
- Input validation on all endpoints
- Structured error responses don't leak sensitive information

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]
