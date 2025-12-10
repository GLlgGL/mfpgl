import json
import re
from typing import Dict, Any
from urllib.parse import urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):
    """
    VK MediaFlow extractor
    - Uses al_video.php (official VK API)
    - Extracts HLS only
    - Rewrites relative VK playlist URLs (expires/…)
    - Fully compatible with VLC / Stremio
    """

    mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)

        # --------------------------------------------------
        # 1) Call VK al_video.php
        # --------------------------------------------------
        ajax_url = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        response = await self._make_request(
            ajax_url,
            method="POST",
            data=self._build_ajax_data(embed_url),
            headers=headers,
        )

        text = response.text.lstrip("<!--")

        try:
            json_data = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON payload")

        master_playlist_url = self._extract_stream(json_data)

        if not master_playlist_url:
            raise ExtractorError("VK: no HLS stream found")

        # --------------------------------------------------
        # 2) Fetch HLS master playlist
        # --------------------------------------------------
        playlist_resp = await self._make_request(
            master_playlist_url,
            method="GET",
            headers={"Referer": "https://vkvideo.ru/"},
        )

        rewritten_playlist = self._rewrite_playlist(
            playlist_resp.text, master_playlist_url
        )

        # --------------------------------------------------
        # 3) Return playlist CONTENT (MediaFlow will proxy)
        # --------------------------------------------------
        return {
            "destination_url": rewritten_playlist,
            "request_headers": {
                "Referer": "https://vkvideo.ru/",
                "User-Agent": UA,
            },
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    # ==================================================
    # Helpers
    # ==================================================

    def _normalize(self, url: str) -> str:
        """
        Normalize all VK URLs into video_ext.php format
        """
        if "video_ext.php" in url:
            return url

        match = re.search(r"video(\-?\d+)_(\d+)", url)
        if not match:
            raise ExtractorError("VK: invalid video URL")

        oid, vid = match.groups()
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = urlparse(embed_url).netloc
        return f"https://{host}/al_video.php"

    def _build_ajax_data(self, embed_url: str) -> Dict[str, str]:
        query = dict(
            part.split("=", 1)
            for part in embed_url.split("?", 1)[1].split("&")
        )

        return {
            "act": "show",
            "al": "1",
            "video": f"{query['oid']}_{query['id']}",
        }

    def _extract_stream(self, json_data: Any) -> str | None:
        """
        Extract HLS master playlist URL from VK payload
        """
        for item in json_data.get("payload", []):
            if isinstance(item, list):
                for block in item:
                    if isinstance(block, dict) and block.get("player"):
                        params = block["player"]["params"][0]
                        return (
                            params.get("hls")
                            or params.get("hls_ondemand")
                            or params.get("hls_live")
                        )
        return None

    def _rewrite_playlist(self, playlist: str, master_url: str) -> str:
        """
        Rewrite VK relative HLS paths so VLC / Stremio can resolve them
        """
        parsed = urlparse(master_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        out = []

        for line in playlist.splitlines():
            line = line.strip()

            if not line:
                continue

            # Absolute URLs
            if line.startswith("http"):
                out.append(line)

            # Absolute path (/expires/…)
            elif line.startswith("/"):
                out.append(base + line)

            # Relative VK path (expires/…)
            elif line.startswith("expires/"):
                out.append(base + "/" + line)

            else:
                out.append(line)

        return "\n".join(out)
