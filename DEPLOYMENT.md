# Deployment Guide

## Prerequisites
- **Docker**: v24.0.0 or higher
- **Docker Compose**: v2.20.0 or higher

## Quick Start
Run the following command from the repository root:
```bash
docker compose up --build -d
```

## Environment Variables
Create a `.env` file based on `.env.example`.

| Variable | Purpose | Required/Optional | Default |
|---|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Required | `postgresql://user:password@db:5432/kspdb` |
| `REDIS_URL` | Redis connection string | Required | `redis://redis:6379/0` |
| `API_PORT` | Port for the FastAPI backend | Optional | `8000` |
| `FRONTEND_PORT` | Port for the Vite/React frontend | Optional | `3000` |
| `CORS_ORIGINS` | Allowed origins for backend API | Optional | `http://localhost:3000` |
| `OPENAI_API_KEY` | Key for AI incident summaries | Optional | *Empty* |

## Verification
Once running, verify the deployment:
1. Open `http://localhost:3000` in your browser. You should see the dark-themed operator map.
2. The backend API documentation is available at `http://localhost:8000/docs`.

## Troubleshooting

### Port 8000 already in use
Change the `API_PORT` in your `.env` file to a different port (e.g., `8080`), and update `CORS_ORIGINS` if necessary.

### PostgreSQL won't start
Usually caused by old, corrupted Docker volumes or permission issues. Run `docker compose down -v` to clear volumes, then restart.

### Frontend shows blank page
Check the browser console. If there are routing issues, verify the Nginx proxy configuration in the frontend Dockerfile. Ensure the `API_URL` environment variable used during the frontend build points to the correct backend host.

### Backend health check fails
Verify the `DATABASE_URL`. The backend waits for the database to become healthy. Check the DB logs using `docker compose logs db`.

### Redis connection refused
Verify the `REDIS_URL`. If Redis restarts, the backend should auto-reconnect, but a manual restart of the backend container may be needed if it loops infinitely.

### Docker build fails on ARM Mac (Apple Silicon)
Add the `--platform linux/amd64` flag to your docker compose commands or specify `platform: linux/amd64` in the `docker-compose.yml` for services that fail to build natively.

### Cold start on free tier
If deployed on a free cloud provider (e.g., Render, Railway), the first request may take 30-60 seconds as the container wakes up.

### CORS errors in browser
Ensure the `CORS_ORIGINS` environment variable in the backend includes the exact URL of your frontend (e.g., `http://localhost:3000` or your production domain). No trailing slashes.

## Resetting to Clean State
To destroy all data and restart from a completely fresh slate:
```bash
docker compose down -v && docker compose up --build
```
