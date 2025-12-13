import re
from typing import Dict, Any
from urllib.parse import urljoin, urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError
from mediaflow_proxy.utils.packed import eval_solver


class StreamWishExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        #
        # 0. Require correct referer (ResolveURL $$ equivalent)
        #
        page_referer = kwargs.get("h_referer")
        if not page_referer:
            raise ExtractorError("StreamWish: missing referer")

        referer = page_referer.rstrip("/") + "/"

        #
        # 1. Load embed page
        #
        response = await self._make_request(url, headers={"Referer": referer})

        #
        # 2. Find iframe
        #
        iframe_match = re.search(
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            response.text,
            re.DOTALL
        )
        iframe_url = iframe_match.group(1) if iframe_match else url

        #
        # 3. Load iframe page
        #
        iframe_response = await self._make_request(
            iframe_url, headers={"Referer": referer}
        )
        html = iframe_response.text

        #
        # 4. Try DIRECT extraction first
        #
        final_url = self._extract_m3u8(html)

        #
        # 5. Fallback: eval_solver (ONLY if packed)
        #
        if not final_url and "eval(function(p,a,c,k,e,d)" in html:
            try:
                final_url = await eval_solver(
                    self,
                    iframe_url,
                    {"Referer": referer},
                    [
                        # absolute URLs
                        r'(https?://[^"\']+\.m3u8[^"\']*)',
                        # relative /stream paths
                        r'(\/stream\/[^"\']+\.m3u8[^"\']*)',
                    ],
                )
            except Exception:
                final_url = None  # NEVER crash

        #
        # 6. Validate
        #
        if not final_url:
            raise ExtractorError("StreamWish: Failed to extract m3u8")

        #
        # 7. Resolve relative URLs
        #
        if final_url.startswith("/"):
            final_url = urljoin(iframe_url, final_url)

        #
        # 8. Set final headers
        #
        origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
        self.base_headers.update({
            "Referer": referer,
            "Origin": origin,
        })

        return {
            "destination_url": final_url,
            "request_headers": self.base_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    @staticmethod
    def _extract_m3u8(text: str) -> str | None:
        m = re.search(r'https?://[^"\']+\.m3u8[^"\']*', text)
        return m.group(0) if m else None
