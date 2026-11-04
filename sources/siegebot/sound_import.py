"""Import sounds from URLs into the server's own sound library.

Accepts direct audio links, single MyInstants sound pages, and MyInstants search/listing pages
(imports every sound on the page). Files are only stored on this server; nothing is redistributed.
"""
import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import unquote, urljoin, urlparse

import aiohttp

from . import sounds as sound_lib

MAX_BYTES = 8 * 1024 * 1024
MAX_PER_PAGE = 100
PLAY_RE = re.compile(r"""play\(\s*['"]([^'"]+\.(?:mp3|ogg|wav|m4a|opus|webm|flac))['"]""", re.I)
MEDIA_RE = re.compile(r"""["'(](/media/sounds/[^"'()\s]+\.(?:mp3|ogg|wav|m4a|opus))""", re.I)
MAGIC = (b"ID3", b"RIFF", b"OggS", b"fLaC", b"\x1aE\xdf\xa3")  # mp3(id3), wav, ogg/opus, flac, webm


def _looks_like_audio(head: bytes) -> bool:
    return head.startswith(MAGIC) or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0) or head[4:8] == b"ftyp"


async def _public_host(url: str) -> bool:
    """Refuse localhost/private targets so the panel can't be used to poke the server's own network."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80),
                                                             type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _same_bytes(path, data):
    try:
        return os.path.getsize(path) == len(data) and open(path, "rb").read() == data
    except OSError:
        return False


def _name_for(url: str) -> str:
    stem = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0].lower()
    stem = re.sub(r"_[A-Za-z0-9]{6,7}$", "", stem)  # drop MyInstants' random dedupe suffix
    stem = re.sub(r"[^a-z0-9_-]+", "_", stem).strip("_-")[:40]
    return stem or "imported"


async def _fetch(http, url, limit=MAX_BYTES):
    async with http.get(url, allow_redirects=True) as r:
        if r.status != 200:
            raise ValueError(f"HTTP {r.status}")
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        data = bytearray()
        async for chunk in r.content.iter_chunked(64 * 1024):
            data += chunk
            if len(data) > limit:
                raise ValueError("too big (max 8 MB)")
        return ctype, bytes(data), str(r.url)


async def _save_audio(http, url, sound_dir, results):
    name = _name_for(url)
    if name in sound_lib.BUILTIN:
        name = f"{name}_import"
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    ext = ext if ext in sound_lib.AUDIO_EXT else ".mp3"
    if not await _public_host(url):
        results["failed"].append(f"{url} (not a public address)")
        return
    try:
        _ctype, data, _final = await _fetch(http, url)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        results["failed"].append(f"{name} ({e or type(e).__name__})")
        return
    if not _looks_like_audio(data[:12]):
        results["failed"].append(f"{name} (not an audio file)")
        return
    # same name already taken? identical file -> skip; different sound -> keep both as name_2, name_3...
    base, n = name, 1
    while True:
        existing = [os.path.join(sound_dir, name + e) for e in sound_lib.AUDIO_EXT
                    if os.path.exists(os.path.join(sound_dir, name + e))]
        if not existing:
            break
        if any(_same_bytes(p, data) for p in existing):
            results["skipped"].append(name)
            return
        n += 1
        name = f"{base[:37]}_{n}"
    with open(os.path.join(sound_dir, name + ext), "wb") as fh:
        fh.write(data)
    results["added"].append(name)


async def import_urls(urls, data_dir):
    """Returns {'added': [...], 'skipped': [...], 'failed': [...]}."""
    sound_dir = sound_lib.sound_dir(data_dir)
    results = {"added": [], "skipped": [], "failed": []}
    headers = {"User-Agent": "SiegeBot sound importer (self-hosted Discord bot)"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), headers=headers) as http:
        for url in urls:
            url = url.strip()
            if not url:
                continue
            if not await _public_host(url):
                results["failed"].append(f"{url} (not a public http(s) address)")
                continue
            path = urlparse(url).path.lower()
            if path.endswith(sound_lib.AUDIO_EXT):
                await _save_audio(http, url, sound_dir, results)
                continue
            try:  # a web page: find the sound links on it (MyInstants sound or search page)
                ctype, data, final = await _fetch(http, url, limit=3 * 1024 * 1024)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                results["failed"].append(f"{url} ({e or type(e).__name__})")
                continue
            if ctype.startswith("audio/"):
                with open(os.path.join(sound_dir, _name_for(final) + ".mp3"), "wb") as fh:
                    fh.write(data)
                results["added"].append(_name_for(final))
                continue
            html = data.decode("utf-8", "replace")
            found = list(dict.fromkeys(PLAY_RE.findall(html) + MEDIA_RE.findall(html)))[:MAX_PER_PAGE]
            if not found:
                results["failed"].append(f"{url} (no sounds found on that page)")
                continue
            for link in found:
                await _save_audio(http, urljoin(final, link), sound_dir, results)
                await asyncio.sleep(0.3)  # be polite to the site
    return results
