import json
import re
from typing import Dict, Any
from urllib.parse import urlparse, urljoin

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "stream"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)

        # --- 1️⃣ Call VK API ---
        response = await self._make_request(
            self._ajax_url(embed_url),
            method="POST",
            data=self._ajax_data(embed_url),
            headers={
                "User-Agent": UA,
                "Referer": "https://vkvideo.ru/",
                "Origin": "https://vkvideo.ru",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        text = response.text.lstrip("<!--")

        try:
            data = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON")

        playlist_url = self._extract_hls(data)
        if not playlist_url:
            raise ExtractorError("VK: no HLS playlist")

        # --- 2️⃣ Fetch playlist ---
        playlist_resp = await self._make_request(
            playlist_url,
            method="GET",
            headers={"User-Agent": UA, "Referer": "https://vkvideo.ru/"},
        )

        # --- 3️⃣ Pick ONE stream URL ---
        stream_url = self._pick_stream(
            playlist_resp.text,
            base_url=playlist_url
        )

        if not stream_url:
            raise ExtractorError("VK: no stream found")

        # --- 4️⃣ Return DIRECT VIDEO STREAM ---
        return {
            "destination_url": stream_url,
            "request_headers": {
                "User-Agent": UA,
                "Referer": "https://vkvideo.ru/",
            },
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    # --------------------------------------------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(\d+)_(\d+)", url)
        if not m:
            raise ExtractorError("Invalid VK URL")

        return f"https://vkvideo.ru/video_ext.php?oid={m[1]}&id={m[2]}"

    def _ajax_url(self, embed: str) -> str:
        host = urlparse(embed).netloc
        return f"https://{host}/al_video.php"

    def _ajax_data(self, embed: str) -> Dict[str, str]:
        qs = dict(part.split("=", 1) for part in embed.split("?", 1)[1].split("&"))
        return {
            "act": "show",
            "al": "1",
            "video": f"{qs['oid']}_{qs['id']}",
        }

    def _extract_hls(self, data: Any) -> str | None:
        for item in data.get("payload", []):
            if isinstance(item, list):
                for block in item:
                    if isinstance(block, dict) and block.get("player"):
                        p = block["player"]["params"][0]
                        return (
                            p.get("hls")
                            or p.get("hls_ondemand")
                            or p.get("hls_live")
                            or params.get("url1080")
                            or params.get("url720")
                            or params.get("url480")
                            or params.get("url360")
                        )
        return None

    def _pick_stream(self, playlist: str, base_url: str) -> str | None:
        """
        Pick highest quality stream and convert to absolute URL
        """
        lines = playlist.splitlines()
        chosen = None

        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF"):
                if i + 1 < len(lines):
                    url = lines[i + 1].strip()
                    if "/expires/" in url:
                        chosen = url  # last = best quality

        if not chosen:
            return None

        # ✅ ABSOLUTE URL FIX
        return urljoin(base_url, chosen)
