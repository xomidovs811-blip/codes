"""
Runs BOTH the FastAPI server (mini app + API) and the Telegram bot polling
loop in a single process. Handy for platforms that only give you one
service/dyno. If your host lets you run two separate processes (recommended
for production), use run_api.py and run_bot.py instead - see Procfile.
"""
import asyncio
import os

import uvicorn

from app.bot import main as run_bot_main
from app.api import app as fastapi_app


async def run_api():
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(run_api(), run_bot_main())


if __name__ == "__main__":
    asyncio.run(main())
