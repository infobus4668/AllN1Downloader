"""Discover and save original files without passing them through a media encoder."""
from __future__ import annotations

import ipaddress
import json
import mimetypes
import re
import socket
import time
import zipfile
from dataclasses import dataclass
from email.message import Message as HeaderMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

import requests

EXTENSIONS = {
    "image": {"jpg", "jpeg", "png", "gif", "webp"},
    "document": {"pdf", "txt", "csv", "epub", "docx", "xlsx", "pptx", "odt", "ods", "odp"},
    "video": {"mp4", "m4v", "mov", "mkv", "webm"},
    "audio": {"mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"},
}
FILE_EXTENSIONS = {ext: kind for kind, extensions in EXTENSIONS.items() for ext in extensions}
MIME_EXTENSIONS = {mimetypes.guess_type(f"file.{ext}")[0]: ext for ext in FILE_EXTENSIONS
                   if mimetypes.guess_type(f"file.{ext}")[0]}
MIME_EXTENSIONS.update({"image/jpeg": "jpg", "video/mp4": "mp4", "audio/mp4": "m4a",
                        "application/epub+zip": "epub", "audio/x-wav": "wav",
                        "application/pdf": "pdf", "text/plain": "txt", "text/csv": "csv",
                        "image/gif": "gif", "image/png": "png", "image/webp": "webp"})
MAX_ITEMS = 100
MAX_FILE = 512 * 1024 * 1024
MAX_JOB_BYTES = 2 * 1024 * 1024 * 1024
MAX_PAGE = 1024 * 1024
OFFICE = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml",
          "epub": "META-INF/container.xml", "odt": "content.xml", "ods": "content.xml", "odp": "content.xml"}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
X_STATUS = re.compile(r"/(?:[A-Za-z0-9_]+|i/web)/status/([0-9]{1,25})(?:/photo/([1-9][0-9]?))?/?$")


class FileDownloadError(ValueError):
    pass


@dataclass(frozen=True)
class FileItem:
    url: str
    name: str
    kind: str
    size: int | None = None


def extension(name: str) -> str:
    return Path(name.lower()).suffix.lstrip(".")


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name).strip(" .")
    suffix = Path(name).suffix[:12]
    stem = (Path(name).stem[:130].strip(" .") or "download")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", stem.split(".")[0]):
        stem = "_" + stem
    return stem + suffix


def public_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None:
            raise ValueError
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        raise FileDownloadError("Could not resolve a valid public HTTP(S) file link.") from None
    ips = [ipaddress.ip_address(addr[4][0]) for addr in addresses]
    if not ips or any(not addr.is_global or addr.is_multicast for addr in ips):
        raise FileDownloadError("File and collection downloads require a public address.")


class PublicAdapter(requests.adapters.HTTPAdapter):
    def send(self, request, *args, **kwargs):
        public_url(request.url)
        response = super().send(request, *args, **kwargs)
        if response.is_redirect:
            # The redirect's body is irrelevant; Requests otherwise buffers it before following Location.
            response.close()
            response._content = b""
            response._content_consumed = True
        return response


def session_for(cookies=None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.max_redirects = 5
    session.mount("http://", PublicAdapter())
    session.mount("https://", PublicAdapter())
    session.headers.update({"User-Agent": "AllN1Downloader/1.1 (public file downloads)", "Accept-Encoding": "identity"})
    if cookies is not None:
        session.cookies.update(cookies)
    return session


def describe_response(response, fallback: str = "") -> FileItem | None:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type in {"text/html", "application/xhtml+xml", "image/svg+xml", "application/json"}:
        return None
    header = HeaderMessage()
    header["Content-Disposition"] = response.headers.get("Content-Disposition", "")
    name = str(header.get_filename() or fallback or unquote(urlsplit(response.url).path.rsplit("/", 1)[-1]))
    ext = extension(name)
    mime_ext = MIME_EXTENSIONS.get(content_type)
    equivalent = ext == mime_ext or {ext, mime_ext} in ({"jpeg", "jpg"}, {"m4v", "mp4"}, {"csv", "txt"})
    if mime_ext and not equivalent:
        ext = mime_ext
        name = (Path(name).stem or "download") + "." + ext
    if ext not in FILE_EXTENSIONS:
        return None
    length = response.headers.get("Content-Length", "")
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    size = int(length) if encoding in {"", "identity"} and re.fullmatch(r"[0-9]{1,16}", length) else None
    return FileItem(response.url, safe_name(name), FILE_EXTENSIONS[ext], size)


def _bounded(response, maximum=MAX_PAGE):
    data = bytearray()
    for chunk in response.iter_content(32768):
        data.extend(chunk)
        if len(data) > maximum:
            raise FileDownloadError("The source page is too large to inspect.")
    return bytes(data)


def _json(session, url, **params):
    with session.get(url, params=params, stream=True, timeout=(5, 12)) as response:
        response.raise_for_status()
        try:
            result = json.loads(_bounded(response))
        except (UnicodeError, ValueError) as error:
            if isinstance(error, FileDownloadError):
                raise
            raise FileDownloadError("The source returned unreadable file metadata.") from None
        if not isinstance(result, dict):
            raise FileDownloadError("The source returned unexpected file metadata.")
        return result


class PageLinks(HTMLParser):
    def __init__(self, kind: str):
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.links = []
        self.refresh = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta" and (fields.get("http-equiv") or "").casefold() == "refresh":
            match = re.fullmatch(r"\s*0(?:\.0+)?\s*;\s*url\s*=\s*(.+?)\s*", fields.get("content") or "", re.I)
            if match and self.refresh is None:
                self.refresh = match[1].strip("\"'")
            return
        if len(self.links) >= MAX_ITEMS:
            return
        if tag == "a":
            urls = (fields.get("href"),)
        elif tag == "meta" and fields.get("property") in {"og:image", "og:image:url", "og:image:secure_url"}:
            urls = (fields.get("content"),)
        elif tag == "img" and self.kind == "image":
            # Prefer the real lazy-loaded image over a placeholder when both are present.
            urls = (fields.get("data-src"), fields.get("src"))
        else:
            return
        for href in urls:
            if not href:
                continue
            href = href.strip()
            try:
                parsed = urlsplit(href)
            except ValueError:
                continue
            if parsed.scheme not in {"", "http", "https"}:
                continue
            if extension(unquote(parsed.path)) in EXTENSIONS.get(self.kind, set()):
                if href not in self.links:
                    self.links.append(href)
                return


def page_is_html(response) -> bool:
    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    return mime in {"text/html", "application/xhtml+xml"}


def same_file_handoff(url: str, target: str | None) -> str | None:
    """Accept an immediate refresh only for the same file with a changed query."""
    if not target:
        return None
    destination = urljoin(url, target)
    original, candidate = urlsplit(url), urlsplit(destination)
    if (original.scheme, original.netloc, original.path) != (candidate.scheme, candidate.netloc, candidate.path):
        return None
    if not candidate.query or candidate.query == original.query or candidate.fragment:
        return None
    return destination


def looks_like_file(url: str) -> bool:
    return extension(unquote(urlsplit(url).path)) in FILE_EXTENSIONS


def known_collection(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    status = x_status(url)
    return host in {"archive.org", "www.archive.org", "arxiv.org", "www.arxiv.org", "commons.wikimedia.org"} or bool(status and status[2])


def x_status(url: str):
    parts = urlsplit(url)
    return X_STATUS.fullmatch(parts.path) if parts.hostname in X_HOSTS else None


def x_photo_item(url: str) -> FileItem | None:
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "pbs.twimg.com":
            return None
        match = re.fullmatch(r"/media/([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9]+))?", parts.path)
    except ValueError:
        return None
    if not match:
        return None
    media_id, file_ext = match.groups()
    file_ext = (file_ext or parse_qs(parts.query).get("format", [""])[0]).lower()
    if file_ext not in EXTENSIONS["image"]:
        return None
    return FileItem(f"https://pbs.twimg.com/media/{media_id}?format={file_ext}&name=orig",
                    f"{media_id}.{file_ext}", "image")


class XPhotoMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            attrs = dict(attrs)
            key = attrs.get("property") or attrs.get("name")
            if key in {"og:url", "og:image", "twitter:image"} and attrs.get("content"):
                self.fields.setdefault(key, attrs["content"])


def x_post_photos(page: str, post_id: str, selected: int | None) -> list[FileItem]:
    matches = {}
    described = set()
    decoder = json.JSONDecoder()
    # X embeds arrays either as JSON data or as JSON text inside a script string.
    for payload in (page, page.replace(r'\"', '"')):
        for marker in re.finditer(r'"(?:media_entities2|extended_entities)"\s*:\s*(?=\[|\{)', payload):
            try:
                data, _ = decoder.raw_decode(payload, marker.end())
            except (ValueError, RecursionError):
                continue
            rows = data.get("media") if isinstance(data, dict) else data
            for row in rows if isinstance(rows, list) else ():
                if not isinstance(row, dict):
                    continue
                try:
                    match = x_status(str(row.get("expanded_url") or ""))
                except ValueError:
                    continue
                if not match or match[1] != post_id or not match[2]:
                    continue
                described.add(int(match[2]))
                if row.get("type") != "photo":
                    continue
                photo = x_photo_item(str(row.get("media_url_https") or ""))
                if photo:
                    matches.setdefault(int(match[2]), photo)
    if selected is None:
        return [matches[index] for index in sorted(matches)]
    if selected in matches:
        return [matches[selected]]
    if selected == 1 and not described:
        metadata = XPhotoMetadata()
        metadata.feed(page)
        try:
            canonical = x_status(metadata.fields.get("og:url", ""))
        except ValueError:
            canonical = None
        if canonical and canonical[1] == post_id:
            photo = x_photo_item(metadata.fields.get("og:image", metadata.fields.get("twitter:image", "")))
            if photo:
                return [photo]
    return []


def resolve_files(url: str, mode: str, session: requests.Session, cancelled=lambda: False):
    """Return original-file candidates and the display name of the source adapter."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path)

    def item(target, name=None, size=None):
        target = urljoin(url, target)
        parsed_target = urlsplit(target)
        if parsed_target.scheme not in {"http", "https"} or not parsed_target.hostname or parsed_target.username is not None:
            return None
        name = name or unquote(parsed_target.path.rsplit("/", 1)[-1])
        kind = FILE_EXTENSIONS.get(extension(name))
        return FileItem(target, safe_name(name), kind, size) if kind else None

    def select(items):
        seen = set()
        result = []
        for candidate in items:
            if cancelled():
                raise InterruptedError
            if candidate and candidate.url not in seen and mode in ("auto", candidate.kind):
                seen.add(candidate.url)
                result.append(candidate)
                if len(result) == MAX_ITEMS:
                    break
        return result

    if mode in {"image", "auto"} and (match := x_status(url)):
        post_id, number = match.groups()
        # X commonly redirects /photo/N to the post. Preserve the requested number separately.
        with session.get(url, stream=True, timeout=(5, 12)) as response:
            response.raise_for_status()
            page = _bounded(response).decode("utf-8", errors="replace")
        photos = x_post_photos(page, post_id, int(number) if number else None)
        if not photos and (number or mode == "image"):
            raise FileDownloadError("X did not expose the requested photo. Try the direct image URL or sign in with a current cookies.txt file.")
        return select(photos), "X photos"

    if host in {"archive.org", "www.archive.org"} and (match := re.fullmatch(r"/details/([\w.-]+)/*", path)):
        identifier = quote(match[1], safe="")
        listing = _json(session, f"https://archive.org/metadata/{identifier}")
        items = (item(f"https://archive.org/download/{identifier}/{quote(row['name'], safe='')}",
                      row["name"], int(row["size"]) if re.fullmatch(r"[0-9]{1,16}", str(row.get("size", ""))) else None)
                 for row in listing.get("files", []) if isinstance(row, dict) and isinstance(row.get("name"), str)
                 and row["name"] and not row.get("private"))
        return select(items), "Internet Archive"
    if host in {"arxiv.org", "www.arxiv.org"} and (match := re.fullmatch(r"/abs/([A-Za-z0-9.\-/]+)", path)):
        return select([item(f"https://arxiv.org/pdf/{match[1]}", match[1].replace("/", "-") + ".pdf")]), "arXiv"
    if host == "commons.wikimedia.org" and path.startswith(("/wiki/File:", "/wiki/Category:")):
        title = path.removeprefix("/wiki/")
        query = ({"titles": title} if title.startswith("File:") else
                 {"generator": "categorymembers", "gcmtitle": title, "gcmtype": "file", "gcmlimit": 50})
        data = _json(session, "https://commons.wikimedia.org/w/api.php", action="query", prop="imageinfo",
                     iiprop="url|size", format="json", formatversion=2, **query)
        entries = (item(row["url"], size=row.get("size")) for page in data.get("query", {}).get("pages", [])
                   for row in page.get("imageinfo", []) if row.get("url"))
        return select(entries), "Wikimedia Commons"

    with session.get(url, stream=True, timeout=(5, 12)) as response:
        response.raise_for_status()
        candidate = describe_response(response)
        if candidate:
            return select([candidate]), "Direct file"
        if page_is_html(response) and (mode in ("image", "document") or looks_like_file(response.url)):
            parser = PageLinks(mode)
            parser.feed(_bounded(response).decode(response.encoding or "utf-8", errors="replace"))
            handoff = same_file_handoff(response.url, parser.refresh) if looks_like_file(response.url) else None
            if handoff:
                with session.get(handoff, stream=True, timeout=(5, 12)) as download:
                    download.raise_for_status()
                    direct = describe_response(download)
                if direct:
                    return select([direct]), "Direct file"
                raise FileDownloadError("The file download page did not deliver the requested file.")
            if mode in ("image", "document"):
                return select(item(urljoin(response.url, href)) for href in parser.links), "Page files"
    return [], "Direct file"


def valid_prefix(ext: str, data: bytes) -> bool:
    if ext in OFFICE:
        return data.startswith(b"PK\x03\x04")
    magic = {"jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",), "png": (b"\x89PNG\r\n\x1a\n",),
             "gif": (b"GIF87a", b"GIF89a"), "pdf": (b"%PDF-",), "flac": (b"fLaC",),
             "ogg": (b"OggS",), "opus": (b"OggS",), "mkv": (b"\x1a\x45\xdf\xa3",), "webm": (b"\x1a\x45\xdf\xa3",)}
    if ext in magic:
        return data.startswith(magic[ext])
    if ext in {"webp", "wav"}:
        return data.startswith(b"RIFF") and data[8:12] == (b"WEBP" if ext == "webp" else b"WAVE")
    if ext in {"mp4", "m4v", "mov", "m4a"}:
        return data[4:8] in (b"ftyp", b"moov", b"mdat", b"wide")
    if ext in {"mp3", "aac"}:
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224)
    if ext in {"txt", "csv"}:
        clean = data.removeprefix(b"\xef\xbb\xbf").lstrip().lower()
        return bool(data) and b"\0" not in data and not clean.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<script"))
    return False


def save_file(item: FileItem, session: requests.Session, folder: Path, cancelled, progress, rate=None, limit=MAX_FILE):
    with session.get(item.url, stream=True, timeout=(5, 15)) as response:
        response.raise_for_status()
        resolved = describe_response(response, item.name)
        if not resolved or resolved.kind != item.kind:
            raise FileDownloadError("The server did not return the expected file type.")
        if (resolved.size or 0) > limit:
            raise FileDownloadError("The file exceeds the remaining download limit.")
        target = folder / resolved.name
        for copy in range(1, MAX_ITEMS + 1):
            if not target.exists():
                break
            target = folder / f"{Path(resolved.name).stem} ({copy}){Path(resolved.name).suffix}"
        if target.exists():
            raise FileDownloadError("Too many files with the same name.")
        temporary = target.with_name(target.name + ".part")
        count = 0
        started = time.monotonic()
        try:
            chunks = response.iter_content(64 * 1024)
            first = next(chunks, b"")
            file_ext = extension(resolved.name)
            if not valid_prefix(file_ext, first):
                raise FileDownloadError("The file contents do not match the advertised type.")
            from itertools import chain
            with temporary.open("xb") as output:
                for chunk in chain((first,), chunks):
                    if cancelled():
                        raise InterruptedError
                    count += len(chunk)
                    if count > limit:
                        raise FileDownloadError("The file exceeds the remaining download limit.")
                    output.write(chunk)
                    progress(count, resolved.size or 0)
                    if rate:
                        deadline = started + count / rate
                        while not cancelled() and (remaining := deadline - time.monotonic()) > 0:
                            time.sleep(min(0.2, remaining))
            if cancelled():
                raise InterruptedError
            if resolved.size is not None and count != resolved.size:
                raise FileDownloadError("The file transfer ended early.")
            if file_ext in OFFICE:
                try:
                    with zipfile.ZipFile(temporary) as archive:
                        archive.getinfo(OFFICE[file_ext])
                except (zipfile.BadZipFile, KeyError):
                    raise FileDownloadError("The downloaded document is not in the expected format.") from None
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return count
