"""Read selected members of a large remote zip via HTTP range requests (used for the official wheelhouse).

Usage: python -m g4agent.remote_zip URL OUT_DIR [--list] [PATTERN ...]
"""
from __future__ import annotations

import fnmatch
import io
import sys
import urllib.request
import zipfile
from pathlib import Path


class HttpRangeFile(io.RawIOBase):
    def __init__(self, url: str):
        req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0"})
        with urllib.request.urlopen(req) as r:
            self.url = r.geturl()  # follow the redirect once to the signed storage URL
            self.size = int(r.headers["Content-Range"].split("/")[-1])
        self.pos = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, off: int, whence: int = 0) -> int:
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.size, self.pos + n) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(req) as r:
            data = r.read()
        self.pos += len(data)
        return data


def main(argv: list[str]) -> int:
    url, out = argv[0], Path(argv[1])
    pats = [a for a in argv[2:] if a != "--list"]
    zf = zipfile.ZipFile(HttpRangeFile(url))  # type: ignore[arg-type]
    for info in zf.infolist():
        if "--list" in argv:
            print(f"{info.file_size:>12d}  {info.filename}")
        elif any(fnmatch.fnmatch(info.filename, p) for p in pats):
            out.mkdir(parents=True, exist_ok=True)
            dest = out / Path(info.filename).name
            dest.write_bytes(zf.read(info))
            print(f"extracted {info.filename} ({info.file_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
