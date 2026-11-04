"""Optional voice-clone service for SiegeBot (runs separately; needs ~4 GB RAM, a GPU makes it fast).

    python3 -m venv venv && venv/bin/pip install -r requirements.txt
    CLONE_TOKEN=some-long-secret venv/bin/python server.py --host 127.0.0.1 --port 8765 --device cpu   # or cuda / mps

Then put http://<host>:8765 and the same token in the SiegeBot panel (Soundboard → Voice clones).
API: POST /synthesize (multipart: text, speaker=<wav file>, exaggeration=0.5) -> audio/wav
Output carries Chatterbox's built-in inaudible watermark, marking it as AI-generated.
"""
import argparse
import asyncio
import io
import os
import tempfile

import torchaudio as ta
from aiohttp import web
from chatterbox.tts import ChatterboxTTS

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--device", default="cpu")
args = parser.parse_args()

TOKEN = os.environ.get("CLONE_TOKEN", "")
print("Loading model (first run downloads ~2 GB)...")
model = ChatterboxTTS.from_pretrained(device=args.device)
lock = asyncio.Lock()


async def health(request):
    return web.json_response({"ok": True, "device": args.device})


async def synthesize(request):
    if TOKEN and request.headers.get("X-Token") != TOKEN:
        raise web.HTTPUnauthorized(text="bad token")
    data = await request.post()
    text = (data.get("text") or "").strip()[:400]
    speaker = data.get("speaker")
    if not text or speaker is None or not hasattr(speaker, "file"):
        raise web.HTTPBadRequest(text="need text and speaker file")
    exaggeration = max(0.25, min(2.0, float(data.get("exaggeration") or 0.5)))
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(speaker.file.read())
    try:
        async with lock:  # one generation at a time keeps RAM sane
            wav = await asyncio.to_thread(model.generate, text, audio_prompt_path=tmp.name, exaggeration=exaggeration)
    finally:
        os.remove(tmp.name)
    buf = io.BytesIO()
    ta.save(buf, wav, model.sr, format="wav")
    return web.Response(body=buf.getvalue(), content_type="audio/wav")


app = web.Application(client_max_size=20 * 1024 * 1024)
app.add_routes([web.get("/health", health), web.post("/synthesize", synthesize)])
web.run_app(app, host=args.host, port=args.port)
