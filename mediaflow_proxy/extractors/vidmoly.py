import re
from typing import Dict, Any
from urllib.parse import urljoin, urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class VidmolyExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str) -> Dict[str, Any]:
        parsed = urlparse(url)
        if not parsed.hostname or not any(parsed.hostname.endswith(d) for d in (
            "vidmoly.net", "vidmoly.me", "vidmoly.to"
        )):
            raise ExtractorError("VIDMOLY: Invalid domain")
        
        # --- Request the main embed page ---
        response = await self._make_request(url)
        html = response.text

        # ✅ Detect redirect to dead-video notice page
        if (
            "notice.php" in response.url   # final URL after redirects
            or "staticmoly" in html and "notice" in html
            or "Video was removed" in html
            or "Video not found" in html
        ):
            raise ExtractorError("VIDMOLY: Video removed")

        # --- Extract HLS URL ---
        match = re.search(r'sources\s*:\s*\[\{file:"([^"]+)"', html)
        if not match:
            raise ExtractorError("VIDMOLY: stream URL not found")

        master_url = match.group(1)

        parsed = urlparse(master_url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            raise ExtractorError("VIDMOLY: Invalid stream URL scheme")

        # --- Fetch master playlist ---
        playlist_resp = await self._make_request(master_url)
        playlist_text = playlist_resp.text

        # Parse variant streams
        variants = re.findall(
            r'#EXT-X-STREAM-INF:.*?BANDWIDTH=(\d+).*?[\r\n]+([^\r\n]+)',
            playlist_text,
        )

        if not variants:
            best_url = master_url
        else:
            variants.sort(key=lambda x: int(x[0]), reverse=True)
            best_url = variants[0][1]

            # Fix relative URLs
            if not best_url.startswith("http"):
                best_url = urljoin(master_url, best_url)

        headers = self.base_headers.copy()
        headers["referer"] = url

        return {
            "destination_url": best_url,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }