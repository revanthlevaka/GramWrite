"""
web_dashboard.py — GramWrite Localhost API & Web Dashboard
Fulfills the promised http://localhost:7878 interface.
"""

import os
import sys
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Callable

from aiohttp import web

from .config_store import save_config
from .engine import GramEngine
from .foundation_models import FOUNDATION_BACKEND_KEY, FOUNDATION_MODEL_ID
from .harper import HARPER_BACKEND_KEY, HARPER_MODEL_ID

logger = logging.getLogger(__name__)

class WebDashboard:
    """
    Minimal aiohttp server for configuration management.
    Syncs with the main app's config dictionary.
    """

    def __init__(self, config: dict, engine: GramEngine, on_update: Optional[Callable[[dict], None]] = None):
        self.config = config
        self.engine = engine
        self.on_update = on_update
        self.app = web.Application()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._latest_suggestion: Optional[dict] = None

        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/api/config', self.handle_get_config)
        self.app.router.add_post('/api/config', self.handle_post_config)
        self.app.router.add_get('/api/models', self.handle_get_models)
        self.app.router.add_get('/api/capabilities', self.handle_get_capabilities)
        self.app.router.add_get('/api/suggestion', self.handle_get_suggestion)

    async def handle_index(self, request):
        for base_dir in self._static_roots():
            static_path = base_dir / 'gramwrite' / 'static' / 'dashboard.html'
            if not static_path.exists():
                continue
            with open(static_path, 'r') as f:
                content = f.read()
            return web.Response(text=content, content_type='text/html')

        checked_paths = [
            str(base_dir / 'gramwrite' / 'static' / 'dashboard.html')
            for base_dir in self._static_roots()
        ]
        logger.error("Web Dashboard index not found in any known location: %s", checked_paths)
        return web.Response(
            text="Dashboard HTML not found. Checked:\n" + "\n".join(checked_paths),
            status=404,
        )

    async def handle_get_config(self, request):
        # Exclude internal keys starting with _
        clean_config = {k: v for k, v in self.config.items() if not k.startswith('_')}
        return web.json_response(clean_config)

    async def handle_post_config(self, request):
        try:
            data = await request.json()
            updated_config = dict(self.config)
            for k, v in data.items():
                if not k.startswith('_'):
                    updated_config[k] = v

            config_path = save_config(updated_config, updated_config.get('_config_path', 'config.yaml'))
            updated_config["_config_path"] = str(config_path)
            logger.info("Config updated via Web Dashboard and saved to %s", config_path)

            self.config.clear()
            self.config.update(updated_config)
            if self.on_update:
                self.on_update(dict(self.config))

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error("Failed to update config via web: %s", e)
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    async def handle_get_models(self, request):
        ollama = await self.engine.list_ollama_models()
        lmstudio = await self.engine.list_lmstudio_models()
        foundation = await self.engine.list_foundation_models()
        harper = await self.engine.list_harper_models()
        models = list(dict.fromkeys(ollama + lmstudio + foundation + harper))
        return web.json_response(models)

    async def handle_get_capabilities(self, request):
        foundation_status = await self.engine.foundation_models_status()
        harper_status = await self.engine.harper_status()
        return web.json_response(
            {
                "platform": sys.platform,
                "apple_foundation_models_backend": FOUNDATION_BACKEND_KEY,
                "apple_foundation_models_model": FOUNDATION_MODEL_ID,
                "apple_foundation_models_supported": foundation_status.supported,
                "apple_foundation_models_available": foundation_status.available,
                "apple_foundation_models_reason": foundation_status.reason,
                "harper_backend": HARPER_BACKEND_KEY,
                "harper_model": HARPER_MODEL_ID,
                "harper_supported": harper_status.supported,
                "harper_available": harper_status.available,
                "harper_reason": harper_status.reason,
            }
        )

    async def handle_get_suggestion(self, request):
        if self._latest_suggestion:
            return web.json_response(self._latest_suggestion)
        return web.json_response({"has_suggestion": False})

    def push_suggestion(self, result: dict):
        """Push a pipeline result to the web dashboard for live polling."""
        self._latest_suggestion = result

    async def start(self, port: int = 7878):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, 'localhost', port)
        await self._site.start()
        logger.info("Web Dashboard started at http://localhost:%d", port)

    async def stop(self):
        if self._site and self._runner:
            try:
                if self._site in self._runner.sites:
                    await self._site.stop()
            except RuntimeError:
                logger.debug("Web Dashboard site was already detached during shutdown.")
        if self._runner:
            await self._runner.cleanup()
        logger.info("Web Dashboard stopped")

    @staticmethod
    def _static_roots() -> list[Path]:
        if hasattr(sys, '_MEIPASS'):
            meipass = Path(sys._MEIPASS)
            candidates = [
                meipass,
                meipass.parent / 'Resources',
                meipass.parent / 'Frameworks',
            ]
        else:
            candidates = [Path(os.path.dirname(os.path.dirname(__file__)))]

        unique_roots: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_roots.append(candidate)
        return unique_roots
