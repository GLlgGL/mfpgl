from urllib.parse import urljoin, urlparse
import re

def parse_hls_playlist(playlist_content: str, base_url: str):
    streams = []
    lines = playlist_content.strip().splitlines()

    parsed = urlparse(base_url)
    base_root = f"{parsed.scheme}://{parsed.netloc}"

    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue

        stream = {}

        attrs = re.findall(
            r'([A-Z-]+)=("([^"]+)"|([^,]+))',
            line
        )

        for key, _, quoted, plain in attrs:
            val = quoted if quoted else plain
            if key == "RESOLUTION":
                try:
                    w, h = map(int, val.split("x"))
                    stream["resolution"] = (w, h)
                except:
                    stream["resolution"] = (0, 0)
            else:
                stream[key.lower()] = val

        # ✅ next line must be absolute
        raw_url = lines[i + 1].strip()

        if raw_url.startswith("/"):
            stream["url"] = base_root + raw_url
        else:
            stream["url"] = urljoin(base_url, raw_url)

        streams.append(stream)

    return streams
