import asyncio
import logging
import os

from aiohttp import web

from .bot import SiegeBot
from .db import DB
from .web import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("siegebot")


class Controller:
    """Owns the bot instance so the panel can (re)start it with a new token."""

    def __init__(self, db):
        self.db = db
        self.bot = None
        self.task = None
        self.error = None

    def token(self):
        return self.db.get("token") or os.environ.get("DISCORD_TOKEN", "")

    def owner_ids(self):
        raw = self.db.get("owner_ids") or os.environ.get("OWNER_IDS", "")
        return [int(x) for x in str(raw).replace(" ", "").split(",") if x.isdigit()]

    async def start(self):
        await self.stop()
        token = self.token()
        if not token:
            self.error = "No bot token configured. Set one in Settings."
            return
        self.error = None
        self.bot = SiegeBot(self.db, self.owner_ids())
        self.task = asyncio.create_task(self._run(self.bot, token))

    async def _run(self, bot, token):
        try:
            await bot.start(token)
        except Exception as e:  # bad token, missing intents, network...
            self.error = f"{type(e).__name__}: {e}"
            self.db.log("error", self.error)
            log.exception("Bot crashed")

    async def stop(self):
        if self.bot and not self.bot.is_closed():
            await self.bot.close()
        if self.task:
            try:
                await asyncio.wait_for(self.task, 10)
            except (asyncio.TimeoutError, Exception):
                pass
        self.bot, self.task = None, None


async def main():
    db = DB(os.path.join(os.environ.get("DATA_DIR", "./data"), "siegebot.db"))
    ctl = Controller(db)
    app = create_app(db, ctl, os.environ.get("BASE_PATH", "/"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8085"))
    await web.TCPSite(runner, "127.0.0.1", port).start()
    log.info("Admin panel on http://127.0.0.1:%s", port)
    await ctl.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
