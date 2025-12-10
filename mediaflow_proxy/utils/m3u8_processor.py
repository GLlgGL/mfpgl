import asyncio
import codecs
import re
from typing import AsyncGenerator
from urllib import parse

from mediaflow_proxy.configs import settings
from mediaflow_proxy.utils.crypto_utils import encryption_handler
from mediaflow_proxy.utils.http_utils import (
    encode_mediaflow_proxy_url,
    encode_stremio_proxy_url,
    get_original_scheme,
)
from mediaflow_proxy.utils.hls_prebuffer import hls_prebuffer


class M3U8Processor:
    def __init__(
        self,
        request,
        key_url: str = None,
        force_playlist_proxy: bool = None,
        key_only_proxy: bool = False,
        no_proxy: bool = False,
    ):
        self.request = request
        self.key_url = parse.urlparse(key_url) if key_url else None
        self.key_only_proxy = key_only_proxy
        self.no_proxy = no_proxy
        self.force_playlist_proxy = force_playlist_proxy

        self.mediaflow_proxy_url = str(
            request.url_for("hls_manifest_proxy").replace(
                scheme=get_original_scheme(request)
            )
        )

        self.playlist_url = None

    # ------------------------------------------------------------
    # MAIN PROCESSORS
    # ------------------------------------------------------------

    async def process_m3u8(self, content: str, base_url: str) -> str:
        self.playlist_url = base_url
        lines = content.splitlines()
        processed_lines = []

        for line in lines:
            if "URI=" in line:
                processed_lines.append(await self.process_key_line(line, base_url))
            elif not line.startswith("#") and line.strip():
                processed_lines.append(await self.proxy_content_url(line, base_url))
            else:
                processed_lines.append(line)

        if settings.enable_hls_prebuffer and "#EXTM3U" in content and self.playlist_url:
            headers = {
                k[2:]: v
                for k, v in self.request.query_params.items()
                if k.startswith("h_")
            }
            asyncio.create_task(
                hls_prebuffer.prebuffer_playlist(self.playlist_url, headers)
            )

        return "\n".join(processed_lines)

    async def process_m3u8_streaming(
        self, content_iterator: AsyncGenerator[bytes, None], base_url: str
    ) -> AsyncGenerator[str, None]:
        self.playlist_url = base_url
        buffer = ""
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        async for chunk in content_iterator:
            buffer += decoder.decode(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
            lines = buffer.split("\n")

            for line in lines[:-1]:
                yield (await self.process_line(line, base_url)) + "\n"

            buffer = lines[-1]

        if buffer:
            yield await self.process_line(buffer, base_url)

    async def process_line(self, line: str, base_url: str) -> str:
        if "URI=" in line:
            return await self.process_key_line(line, base_url)
        if not line.startswith("#") and line.strip():
            return await self.proxy_content_url(line, base_url)
        return line

    # ------------------------------------------------------------
    # KEY HANDLING
    # ------------------------------------------------------------

    async def process_key_line(self, line: str, base_url: str) -> str:
        uri_match = re.search(r'URI="([^"]+)"', line)
        if not uri_match:
            return line

        original = uri_match.group(1)
        resolved = self._resolve_url(original, base_url)

        if self.no_proxy:
            return line.replace(original, resolved)

        proxied = await self.proxy_url(resolved, base_url, use_full_url=True)
        return line.replace(original, proxied)

    # ------------------------------------------------------------
    # ✅ CRITICAL FIX — VK /expires/
    # ------------------------------------------------------------

    async def proxy_content_url(self, url: str, base_url: str) -> str:
        full_url = self._resolve_url(url, base_url)

        if self.no_proxy:
            return full_url

        if self.key_only_proxy and not full_url.endswith((".m3u8", ".m3u")):
            return full_url

        parsed = parse.urlparse(full_url)

        if (
            self.force_playlist_proxy
            or parsed.path.endswith((".m3u", ".m3u8", ".m3u_plus"))
        ):
            return await self.proxy_url(full_url, base_url, use_full_url=True)

        routing = settings.m3u8_content_routing

        if routing == "direct":
            return full_url

        if routing == "stremio" and settings.stremio_proxy_url:
            headers = {
                k[2:]: v
                for k, v in self.request.query_params.items()
                if k.startswith("h_")
            }
            return encode_stremio_proxy_url(
                settings.stremio_proxy_url,
                full_url,
                request_headers=headers,
            )

        return await self.proxy_url(full_url, base_url, use_full_url=True)

    # ------------------------------------------------------------
    # ✅ URL RESOLUTION (THE FIX)
    # ------------------------------------------------------------

    def _resolve_url(self, url: str, base_url: str) -> str:
        base_parsed = parse.urlparse(base_url)
        origin = f"{base_parsed.scheme}://{base_parsed.netloc}"

        if url.startswith("/"):
            return origin + url

        return parse.urljoin(base_url, url)

    # ------------------------------------------------------------
    # MEDIAFLOW PROXY
    # ------------------------------------------------------------

    async def proxy_url(self, url: str, base_url: str, use_full_url: bool = False) -> str:
        full_url = url if use_full_url else parse.urljoin(base_url, url)

        query_params = dict(self.request.query_params)
        has_encrypted = query_params.pop("has_encrypted", False)

        for k in list(query_params.keys()):
            if k.startswith("r_"):
                query_params.pop(k)

        query_params.pop("force_playlist_proxy", None)

        return encode_mediaflow_proxy_url(
            self.mediaflow_proxy_url,
            "",
            full_url,
            query_params=query_params,
            encryption_handler=encryption_handler if has_encrypted else None,
        )
