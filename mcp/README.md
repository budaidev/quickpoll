# quickpoll MCP server

A small MCP server (streamable HTTP, `/mcp`) that drives quickpoll through its REST API:
`format_guide`, `list_rooms`, `create_room`, `list_sets`, `get_set`, `import_set`, `delete_set`, `get_results`.

It authenticates to the app with a bearer token from the app's `API_TOKENS` (`token=username`,
see `backend/accounts/token_auth.py`), so it acts as that user. Its own clients send `Authorization: Bearer $MCP_TOKEN`.

Env: `QUICKPOLL_API` (internal base URL, default `http://app:8000`), `QUICKPOLL_API_TOKEN`, `PUBLIC_BASE_URL`
(for the links it returns), `MCP_TOKEN`. Build with this directory as context; run beside the app on its network.
