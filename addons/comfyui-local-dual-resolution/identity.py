"""Identify the input folder before submitting work to a manually started server."""
from pathlib import Path
from aiohttp import web
import folder_paths
from server import PromptServer

@PromptServer.instance.routes.get('/image-to-motion/identity')
async def identity(request):
    return web.json_response({'input_directory':str(Path(folder_paths.get_input_directory()).resolve())})
