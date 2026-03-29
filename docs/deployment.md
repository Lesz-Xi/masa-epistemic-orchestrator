# Deployment

This repository ships a reference Docker setup in `docker-compose.example.yml`.

Before deploying:

- create a real `.env` from `.env.example`
- set `MCP_CLIENT_SECRET` and `MCP_TOKEN_SECRET`
- set `SEMANTIC_SCHOLAR_API_KEY` if you want higher upstream rate limits
- verify `MCP_PUBLIC_HOST` matches the externally reachable MCP URL

Recommended public exposure model:

- expose the MCP HTTP server only with OAuth credentials configured
- keep the console behind an SSH tunnel or equivalent private access
- keep secrets out of the repository and CI logs
