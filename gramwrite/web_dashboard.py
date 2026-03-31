"""
web_dashboard.py — GramWrite Localhost API & Web Dashboard
Fulfills the promised http://localhost:7878 interface.
"""

import os
import sys
import json
import logging
import asyncio
from typing import Optional, Callable

from aiohttp import web
import yaml

from .engine import GramEngine

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
        
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/api/config', self.handle_get_config)
        self.app.router.add_post('/api/config', self.handle_post_config)
        self.app.router.add_get('/api/models', self.handle_get_models)

    async def handle_index(self, request):
        if hasattr(sys, '_MEIPASS'):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(__file__))

        static_path = os.path.join(base_dir, 'gramwrite', 'static', 'dashboard.html')
        try:
            with open(static_path, 'r') as f:
                content = f.read()
            return web.Response(text=content, content_type='text/html')
        except FileNotFoundError:
            logger.error("Web Dashboard index not found at %s", static_path)
            return web.Response(text=f"Dashboard HTML not found at {static_path}", status=404)

    async def handle_get_config(self, request):
        # Exclude internal keys starting with _
        clean_config = {k: v for k, v in self.config.items() if not k.startswith('_')}
        return web.json_response(clean_config)

    async def handle_post_config(self, request):
        try:
            data = await request.json()
            # Update live config
            for k, v in data.items():
                if k in self.config and not k.startswith('_'):
                    self.config[k] = v
            
            # Persist to disk
            config_path = self.config.get('_config_path', 'config.yaml')
            save_data = {k: v for k, v in self.config.items() if not k.startswith('_')}
            
            with open(config_path, 'w') as f:
                yaml.dump(save_data, f, default_flow_style=False, allow_unicode=True)
            
            logger.info("Config updated via Web Dashboard and saved to %s", config_path)
            
            if self.on_update:
                self.on_update(self.config)
            
            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error("Failed to update config via web: %s", e)
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    async def handle_get_models(self, request):
        ollama = await self.engine.list_ollama_models()
        lmstudio = await self.engine.list_lmstudio_models()
        models = list(dict.fromkeys(ollama + lmstudio))
        return web.json_response(models)

    async def start(self, port: int = 7878):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, 'localhost', port)
        await self._site.start()
        logger.info("Web Dashboard started at http://localhost:%d", port)

    async def stop(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Web Dashboard stopped")
