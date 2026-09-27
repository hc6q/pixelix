from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import bleach
import markdown
import qrcode
import qrcode.image.svg
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer_for_filename
from pygments.util import ClassNotFound

BASE = Path(__file__).resolve().parent
APP_NAME = os.getenv("APP_NAME", "PasteDrop")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8766"))
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "192.168.1.24").strip()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "/data/database.db"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "2147483648"))
DEFAULT_EXPIRATION = int(os.getenv("DEFAULT_EXPIRATION", "86400"))
EXPIRATIONS = {600: "10 minutos", 3600: "1 hora", 86400: "1 dia", 604800: "7 dias", 2592000: "30 dias", 0: "Nunca"}
LEASE_SECONDS = 1800
CHUNK = 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_-]{5,16}$")
SAFE_IMAGE = {"image/png", "image/jpeg", "image/gif", "image/webp"}
SAFE_VIDEO = {"video/mp4", "video/webm"}


def base_url() -> str:
    host = PUBLIC_HOST.removeprefix("http://").removeprefix("https://").split("/")[0].split(":")[0]
    return f"http://{host}:{PORT}"


def db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS pastes (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT, text_content TEXT,
            filename TEXT, stored_filename TEXT, mime_type TEXT, file_size INTEGER NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER, password_hash TEXT,
            views INTEGER NOT NULL DEFAULT 0, delete_after_view INTEGER NOT NULL DEFAULT 0,
            delete_key_hash TEXT NOT NULL, claimed_at INTEGER, claimed_token_hash TEXT,
            claimed_until INTEGER)""")
        conn.execute("CREATE INDEX IF NOT EXISTS pastes_expire ON pastes(expires_at)")
    secret_path = DATABASE_PATH.parent / ".cookie_secret"
    try:
        with secret_path.open("xb") as f:
            f.write(secrets.token_bytes(32))
        secret_path.chmod(0o600)
    except FileExistsError:
        pass


def remove_row(conn, row):
    conn.execute("DELETE FROM pastes WHERE id=?", (row["id"],))
    if row["stored_filename"]:
        (UPLOAD_DIR / row["stored_filename"]).unlink(missing_ok=True)


def cleanup():
    now = int(time.time())
    with db() as conn:
        rows = conn.execute("SELECT * FROM pastes WHERE (expires_at IS NOT NULL AND expires_at <= ?) OR (claimed_until IS NOT NULL AND claimed_until <= ?)", (now, now)).fetchall()
        for row in rows:
            remove_row(conn, row)


async def cleanup_loop():
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(cleanup)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cleanup()
    task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    })
    return response


def password_hash(value: str):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, 260000)
    return f"{salt.hex()}:{digest.hex()}"


def password_valid(value: str, stored: str):
    try:
        salt, digest = stored.split(":")
        actual = hashlib.pbkdf2_hmac("sha256", value.encode(), bytes.fromhex(salt), 260000)
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_name(name: str | None) -> str:
    name = (name or "arquivo").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    return (name[:180] or "arquivo")


def sniff_mime(header: bytes, name: str) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if header.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")): return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP": return "image/webp"
    if header.startswith(b"\x1a\x45\xdf\xa3"): return "video/webm"
    if len(header) > 12 and header[4:8] == b"ftyp": return "video/mp4"
    if header.startswith(b"%PDF-"): return "application/pdf"
    if header.startswith(b"PK\x03\x04"): return "application/zip"
    if header.startswith(b"\x1f\x8b"): return "application/gzip"
    if header.startswith(b"7z\xbc\xaf\x27\x1c"): return "application/x-7z-compressed"
    if header.startswith(b"Rar!\x1a\x07"): return "application/vnd.rar"
    # Untrusted types are always downloaded, regardless of their claimed extension.
    return "application/octet-stream"


def validate_expiration(value: int):
    if value not in EXPIRATIONS:
        raise HTTPException(422, "Expiração inválida")
    return int(time.time()) + value if value else None


def row_for(pid: str):
    if not ID_RE.fullmatch(pid): raise HTTPException(404, "Link não encontrado")
    with db() as conn:
        row = conn.execute("SELECT * FROM pastes WHERE id=?", (pid,)).fetchone()
        if not row: raise HTTPException(404, "Link não encontrado")
        now = int(time.time())
        if (row["expires_at"] is not None and row["expires_at"] <= now) or (row["claimed_until"] is not None and row["claimed_until"] <= now):
            remove_row(conn, row)
            raise HTTPException(404, "Link não encontrado")
        return dict(row)


def grant_cookie(pid: str): return f"pd_auth_{pid}"
def claim_cookie(pid: str): return f"pd_view_{pid}"


def access_token(row: dict):
    secret = (DATABASE_PATH.parent / ".cookie_secret").read_bytes()
    return hmac.new(secret, (row["id"] + ":" + row["password_hash"]).encode(), hashlib.sha256).hexdigest()


def authorized(row: dict, request: Request):
    if not row["password_hash"]: return True
    token = request.cookies.get(grant_cookie(row["id"]), "")
    return bool(token and hmac.compare_digest(token, access_token(row)))


def require_auth(row, request):
    if not authorized(row, request):
        raise HTTPException(403, "Senha necessária")


def claimed(row, request):
    token = request.cookies.get(claim_cookie(row["id"]), "")
    return bool(token and row["claimed_token_hash"] and hmac.compare_digest(token_hash(token), row["claimed_token_hash"]))


def record_view(row, request):
    """Atomic first claim; only explicit page/raw/API content requests count."""
    pid = row["id"]
    now = int(time.time())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM pastes WHERE id=?", (pid,)).fetchone()
        if not current or (current["expires_at"] is not None and current["expires_at"] <= now):
            conn.execute("ROLLBACK")
            raise HTTPException(404, "Link não encontrado")
        if current["claimed_at"]:
            if not claimed(current, request) or current["claimed_until"] <= now:
                conn.execute("ROLLBACK")
                raise HTTPException(404, "Link não encontrado")
            conn.execute("COMMIT")
            return dict(current), None
        token = secrets.token_urlsafe(32) if current["delete_after_view"] else None
        if token:
            conn.execute("UPDATE pastes SET views=views+1, claimed_at=?, claimed_token_hash=?, claimed_until=? WHERE id=?", (now, token_hash(token), now + LEASE_SECONDS, pid))
        else:
            conn.execute("UPDATE pastes SET views=views+1 WHERE id=?", (pid,))
        updated = conn.execute("SELECT * FROM pastes WHERE id=?", (pid,)).fetchone()
        conn.execute("COMMIT")
        return dict(updated), token


def set_claim(response, row, token):
    if token:
        response.set_cookie(claim_cookie(row["id"]), token, max_age=LEASE_SECONDS, httponly=True, samesite="lax", path="/")


def public_record(row):
    return {k: row[k] for k in ("id", "type", "title", "filename", "mime_type", "file_size", "created_at", "expires_at", "views", "delete_after_view")}


def links(pid: str):
    url = base_url() + "/" + pid
    return {"url": url, "raw_url": base_url() + "/raw/" + pid}


def create_row(*, typ, title, text_content, filename, stored_filename, mime_type, file_size, expires_at, password, delete_after_view):
    key = secrets.token_urlsafe(32)
    with db() as conn:
        for _ in range(10):
            pid = secrets.token_urlsafe(6).rstrip("=")
            try:
                conn.execute("""INSERT INTO pastes (id,type,title,text_content,filename,stored_filename,mime_type,file_size,created_at,expires_at,password_hash,delete_after_view,delete_key_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (pid, typ, title[:160] if title else None, text_content, filename, stored_filename, mime_type, file_size, int(time.time()), expires_at, password_hash(password) if password else None, int(delete_after_view), token_hash(key)))
                return {"id": pid, **links(pid), "delete_token": key}
            except sqlite3.IntegrityError:
                continue
    raise HTTPException(500, "Não foi possível criar o link")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {"app_name": APP_NAME, "expirations": EXPIRATIONS, "default_expiration": DEFAULT_EXPIRATION if DEFAULT_EXPIRATION in EXPIRATIONS else 86400, "max_upload_size": MAX_UPLOAD_SIZE})


@app.post("/api/paste")
def create_paste(payload: dict):
    content = payload.get("text_content")
    if not isinstance(content, str) or not content.strip(): raise HTTPException(422, "Cole algum texto")
    size = len(content.encode("utf-8"))
    if size > min(MAX_UPLOAD_SIZE, 10 * 1024 * 1024): raise HTTPException(413, "Texto grande demais")
    title = payload.get("title") or ""
    password = payload.get("password") or ""
    if not isinstance(title, str) or not isinstance(password, str) or len(password) > 256: raise HTTPException(422, "Dados inválidos")
    kind = payload.get("format", "text")
    if kind not in ("text", "code", "markdown"): raise HTTPException(422, "Formato inválido")
    expiration = payload.get("expiration", DEFAULT_EXPIRATION)
    if type(expiration) is not int: raise HTTPException(422, "Expiração inválida")
    result = create_row(typ=kind, title=title, text_content=content, filename=None, stored_filename=None, mime_type="text/plain", file_size=size, expires_at=validate_expiration(expiration), password=password, delete_after_view=bool(payload.get("delete_after_view", False)))
    return JSONResponse(result, status_code=201)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), title: str = Form(""), expiration: int = Form(DEFAULT_EXPIRATION), password: str = Form(""), delete_after_view: bool = Form(False)):
    expires_at = validate_expiration(expiration)
    if len(password) > 256: raise HTTPException(422, "Senha longa demais")
    name = safe_name(file.filename)
    stored = secrets.token_hex(24)
    path = UPLOAD_DIR / stored
    size = 0
    header = b""
    try:
        with path.open("xb") as target:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE: raise HTTPException(413, "Arquivo excede o limite")
                if len(header) < 32: header = (header + chunk)[:32]
                target.write(chunk)
        if not size: raise HTTPException(422, "Arquivo vazio")
        mime = sniff_mime(header, name)
        kind = "image" if mime in SAFE_IMAGE else "video" if mime in SAFE_VIDEO else "file"
        result = create_row(typ=kind, title=title, text_content=None, filename=name, stored_filename=stored, mime_type=mime, file_size=size, expires_at=expires_at, password=password, delete_after_view=delete_after_view)
        return JSONResponse(result, status_code=201)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get("/api/paste/{pid}")
def api_get(pid: str, request: Request, response: Response):
    row = row_for(pid)
    require_auth(row, request)
    row, token = record_view(row, request)
    set_claim(response, row, token)
    result = {**public_record(row), **links(pid)}
    if row["type"] in ("text", "code", "markdown"):
        result["text_content"] = row["text_content"]
    return result


@app.delete("/api/paste/{pid}")
def api_delete(pid: str, x_delete_token: str = Header(default="")):
    row = row_for(pid)
    if not x_delete_token or not hmac.compare_digest(token_hash(x_delete_token), row["delete_key_hash"]):
        raise HTTPException(403, "Chave de exclusão inválida")
    with db() as conn:
        remove_row(conn, row)
    return {"deleted": True}


@app.post("/{pid}/unlock")
def unlock(pid: str, password: str = Form(...)):
    row = row_for(pid)
    if not row["password_hash"] or not password_valid(password, row["password_hash"]):
        raise HTTPException(403, "Senha incorreta")
    response = RedirectResponse("/" + pid, status_code=303)
    response.set_cookie(grant_cookie(pid), access_token(row), httponly=True, samesite="lax", max_age=86400, path="/")
    return response


def rendered_text(row):
    content = row["text_content"]
    if row["type"] == "markdown":
        untrusted = markdown.markdown(content, extensions=["fenced_code", "tables"])
        allowed = set(bleach.sanitizer.ALLOWED_TAGS) | {"p", "pre", "code", "h1", "h2", "h3", "h4", "hr", "br", "table", "thead", "tbody", "tr", "th", "td", "img", "del"}
        return bleach.clean(untrusted, tags=allowed, attributes={"a": ["href", "title"], "img": ["src", "alt", "title"]}, protocols=["http", "https", "mailto"], strip=True)
    if row["type"] == "code":
        try: lexer = guess_lexer_for_filename(row["title"] or "snippet.txt", content)
        except ClassNotFound: lexer = TextLexer()
        return highlight(content, lexer, HtmlFormatter(nowrap=False))
    return html.escape(content)


@app.get("/{pid}", response_class=HTMLResponse)
def view(pid: str, request: Request):
    row = row_for(pid)
    if not authorized(row, request):
        if row["claimed_at"]: raise HTTPException(404, "Link não encontrado")
        return templates.TemplateResponse(request, "password.html", {"app_name": APP_NAME, "pid": pid})
    row, token = record_view(row, request)
    response = templates.TemplateResponse(request, "view.html", {"app_name": APP_NAME, "paste": row, "links": links(pid), "rendered": rendered_text(row) if row["text_content"] is not None else None, "expires_label": datetime.fromtimestamp(row["expires_at"], timezone.utc).isoformat() if row["expires_at"] else "Nunca", "created_label": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat()})
    set_claim(response, row, token)
    return response


def file_stream(path, start, end):
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining:
            chunk = f.read(min(CHUNK, remaining))
            if not chunk: break
            remaining -= len(chunk)
            yield chunk


@app.get("/raw/{pid}")
def raw(pid: str, request: Request):
    row = row_for(pid)
    require_auth(row, request)
    if row["delete_after_view"] and not row["claimed_at"]:
        row, token = record_view(row, request)
    else:
        token = None
        if row["claimed_at"] and not claimed(row, request): raise HTTPException(404, "Link não encontrado")
    if row["text_content"] is not None:
        response = Response(row["text_content"], media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})
        set_claim(response, row, token)
        return response
    path = UPLOAD_DIR / row["stored_filename"]
    if not path.is_file(): raise HTTPException(404, "Arquivo não encontrado")
    inline = row["mime_type"] in SAFE_IMAGE | SAFE_VIDEO
    disposition = "inline" if inline else "attachment"
    encoded = quote(row["filename"])
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}", "Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    range_value = request.headers.get("range")
    if range_value:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_value.strip())
        if not match or not any(match.groups()):
            raise HTTPException(416, "Range inválido", headers={"Content-Range": f"bytes */{row['file_size']}"})
        a, b = match.groups()
        size = row["file_size"]
        if a:
            start = int(a)
            end = int(b) if b else size - 1
        else:
            suffix = int(b)
            start, end = max(0, size - suffix), size - 1
        if start >= size or end < start or end >= size or (not a and int(b) == 0):
            raise HTTPException(416, "Range inválido", headers={"Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        response = StreamingResponse(file_stream(path, start, end), status_code=206, media_type=row["mime_type"], headers=headers)
    else:
        response = FileResponse(path, media_type=row["mime_type"], headers=headers)
    set_claim(response, row, token)
    return response


@app.get("/qr/{pid}")
def qr(pid: str, request: Request):
    row_for(pid)
    image = qrcode.make(links(pid)["url"], image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    stream = io.BytesIO()
    image.save(stream)
    return Response(stream.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store", "Content-Disposition": "attachment; filename=qr.svg"})
