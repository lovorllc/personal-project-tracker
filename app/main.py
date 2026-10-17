from __future__ import annotations

import os
import re
import secrets
import sqlite3
import io
import uuid
import hashlib
import hmac
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.datastructures import UploadFile
from starlette.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
APP_DIR = BASE_DIR / "app"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "site.db"))
UPLOAD_DIRECTORY = Path(os.getenv("UPLOAD_DIRECTORY", BASE_DIR / "data" / "uploads"))
UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
LANGUAGES = {"en", "hr"}
SITE_COPY_DEFAULTS = (
    ("site_title", "Browser title", "Projects by Lovro", "Projekti Lovre"),
    ("home_label", "Home navigation label", "Home", "Početna"),
    ("projects_label", "Projects navigation label", "Projects", "Projekti"),
    ("all_projects_label", "All projects label", "All projects", "Svi projekti"),
    ("about_label", "About navigation label", "About", "O meni"),
    ("navigation_label", "Navigation accessibility label", "Main navigation", "Glavna navigacija"),
    ("home_heading", "Homepage heading", "Projects by Lovro", "Projekti Lovre"),
    ("home_intro", "Homepage introduction", "Selected work and things I've made.", "Odabrani projekti i stvari koje sam izradio."),
    ("recent_heading", "Recent projects heading", "Selected projects", "Izdvojeni projekti"),
    ("browse_projects", "Browse projects link", "All projects", "Svi projekti"),
    ("empty_projects", "Empty project list", "No projects to show yet.", "Trenutačno nema projekata za prikaz."),
    ("empty_projects_hint", "Empty project list note", "Check back later.", "Navratite ponovno kasnije."),
    ("home_about_link", "Homepage About link", "About Lovro", "O Lovri"),
    ("footer_text", "Scrolling footer text", "Projects, ideas, and things I've made.", "Projekti, ideje i stvari koje sam izradio."),
    ("project_archive_heading", "Project archive heading", "All projects", "Svi projekti"),
    ("project_archive_intro", "Project archive introduction", "A selection of projects I've worked on.", "Izbor projekata na kojima sam radio."),
    ("category_pages_heading", "Category page links heading", "Pages in this category", "Stranice u ovoj kategoriji"),
    ("empty_category", "Empty category message", "No projects in this category yet.", "U ovoj kategoriji još nema projekata."),
    ("back_to_projects", "Back to projects link", "Back to projects", "Natrag na projekte"),
    ("project_label", "Project type label", "Project", "Projekt"),
    ("uncategorized", "Uncategorized label", "Uncategorized", "Bez kategorije"),
    ("project_details", "Project details heading", "Details", "Detalji"),
    ("project_gallery", "Project gallery accessible label", "Project image gallery", "Galerija slika projekta"),
    ("close_gallery", "Close project image label", "Close image", "Zatvori sliku"),
    ("search_placeholder", "Project search placeholder", "Search projects or type /category", "Pretraži projekte ili upiši /kategorija"),
    ("search_button", "Project search button", "Search", "Traži"),
    ("search_empty", "No search results message", "No matching projects found.", "Nema pronađenih projekata."),
    ("search_category", "Category search indicator", "Category", "Kategorija"),
    ("search_text", "Text search indicator", "Search results", "Rezultati pretrage"),
    ("search_hint", "Search instructions", "Search project text or start with / to search categories", "Pretraži tekst projekta ili započni s / za kategorije"),
    ("visit_project", "Project link button", "Visit project", "Otvori projekt"),
    ("project_more_soon", "Missing project details", "More details coming soon.", "Više detalja uskoro."),
    ("section_label", "Page section label", "About this page", "O ovoj stranici"),
    ("not_found", "Not-found message", "Page not found", "Stranica nije pronađena"),
    ("home_link", "Return home link", "Home", "Početna"),
    ("switch_to_hr", "Language toggle accessible label (English page)", "Switch language to Croatian", ""),
    ("switch_to_en", "Language toggle accessible label (Croatian page)", "", "Promijeni jezik na engleski"),
    ("menu_open", "Open menu accessibility label", "Open navigation", "Otvori navigaciju"),
    ("menu_close", "Close menu accessibility label", "Close navigation", "Zatvori navigaciju"),
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Pixel Portfolio", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "local-development-only-change-me"),
    session_cookie="portfolio_session",
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.get("/uploads/{filename}")
def uploaded_file(filename: str) -> FileResponse:
    path = (UPLOAD_DIRECTORY / filename).resolve()
    if path.parent != UPLOAD_DIRECTORY.resolve() or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/webp")

templates = Jinja2Templates(directory=APP_DIR / "templates")


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with closing(connect()) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                name_hr TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                title_hr TEXT NOT NULL DEFAULT '',
                summary_hr TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                body_hr TEXT NOT NULL DEFAULT '',
                link TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL DEFAULT '',
                title_hr TEXT NOT NULL DEFAULT '',
                body_hr TEXT NOT NULL DEFAULT '',
                parent_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
                parent_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                is_dropdown INTEGER NOT NULL DEFAULT 0,
                is_builtin INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS site_copy (
                key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                text_en TEXT NOT NULL DEFAULT '',
                text_hr TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS project_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                image_path TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS project_categories (
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                PRIMARY KEY (project_id, category_id)
            );
            CREATE TABLE IF NOT EXISTS project_sections (
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                PRIMARY KEY (project_id, section_id)
            );
            CREATE TABLE IF NOT EXISTS admin_credentials (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL
            );
            """
        )
        for table, column in (
            ("categories", "name_hr TEXT NOT NULL DEFAULT ''"),
            ("projects", "title_hr TEXT NOT NULL DEFAULT ''"),
            ("projects", "summary_hr TEXT NOT NULL DEFAULT ''"),
            ("projects", "body_hr TEXT NOT NULL DEFAULT ''"),
            ("projects", "image_path TEXT NOT NULL DEFAULT ''"),
            ("sections", "title_hr TEXT NOT NULL DEFAULT ''"),
            ("sections", "body_hr TEXT NOT NULL DEFAULT ''"),
            ("sections", "parent_id INTEGER REFERENCES sections(id) ON DELETE SET NULL"),
            ("sections", "parent_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL"),
            ("sections", "is_dropdown INTEGER NOT NULL DEFAULT 0"),
        ):
            existing_columns = {item["name"] for item in db.execute(f"PRAGMA table_info({table})")}
            column_name = column.split()[0]
            if column_name not in existing_columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        db.execute(
            "INSERT OR IGNORE INTO sections (title, slug, body, title_hr, body_hr, is_builtin) VALUES (?, ?, ?, ?, ?, 1)",
            ("About", "about", "A little more about me, soon.", "O meni", "Uskoro više o meni."),
        )
        db.execute(
            "UPDATE sections SET body = ? WHERE slug = 'about' AND body = ?",
            ("A little more about me, soon.", "This is your space. Add a few words about yourself from the admin panel."),
        )
        db.execute(
            "INSERT OR IGNORE INTO project_categories (project_id, category_id) SELECT id, category_id FROM projects WHERE category_id IS NOT NULL"
        )
        db.execute("UPDATE sections SET parent_category_id = NULL WHERE parent_category_id IS NOT NULL")
        db.executemany(
            "INSERT OR IGNORE INTO site_copy (key, label, text_en, text_hr) VALUES (?, ?, ?, ?)",
            SITE_COPY_DEFAULTS,
        )
        if db.execute("SELECT 1 FROM admin_credentials WHERE id = 1").fetchone() is None:
            configured_username = os.getenv("ADMIN_USERNAME", "")
            configured_password = os.getenv("ADMIN_PASSWORD", "")
            if configured_username and configured_password:
                db.execute(
                    "INSERT INTO admin_credentials (id, username, password_hash) VALUES (1, ?, ?)",
                    (configured_username, hash_password(configured_password)),
                )
        db.execute(
            "UPDATE site_copy SET label = ?, text_en = ?, text_hr = ? WHERE key = 'footer_text' AND text_en IN (?, ?)",
            ("Scrolling footer text", "Projects, ideas, and things I've made.", "Projekti, ideje i stvari koje sam izradio.", "© Lovro", "Personal projects"),
        )
        db.commit()


def rows(query: str, values: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with closing(connect()) as db:
        return list(db.execute(query, values).fetchall())


def row(query: str, values: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with closing(connect()) as db:
        return db.execute(query, values).fetchone()


def project_query(where: str = "", values: tuple[Any, ...] = (), limit: int | None = None) -> list[sqlite3.Row]:
    query = """SELECT projects.*,
                       (SELECT GROUP_CONCAT(categories.name, ', ')
                        FROM project_categories JOIN categories ON categories.id = project_categories.category_id
                        WHERE project_categories.project_id = projects.id) AS category_name,
                       (SELECT GROUP_CONCAT(categories.name_hr, ', ')
                        FROM project_categories JOIN categories ON categories.id = project_categories.category_id
                        WHERE project_categories.project_id = projects.id) AS category_name_hr
                FROM projects"""
    if where:
        query += f" WHERE {where}"
    query += " ORDER BY datetime(projects.created_at) DESC, projects.id DESC"
    if limit is not None:
        query += " LIMIT ?"
        values += (limit,)
    return rows(query, values)


def projects_for_section(section_id: int) -> list[sqlite3.Row]:
    return project_query(
        "projects.id IN (SELECT project_id FROM project_sections WHERE section_id = ?)",
        (section_id,),
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or secrets.token_hex(3)


def unique_slug(value: str, table: str, item_id: int | None = None) -> str:
    base = slugify(value)
    candidate = base
    suffix = 2
    while True:
        query = f"SELECT id FROM {table} WHERE slug = ?"
        values: tuple[Any, ...] = (candidate,)
        if item_id is not None:
            query += " AND id != ?"
            values += (item_id,)
        if row(query, values) is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def current_language(request: Request) -> str:
    language = request.session.get("language", "en")
    return language if language in LANGUAGES else "en"


def localized(record: sqlite3.Row | dict[str, Any] | None, fields: tuple[str, ...], language: str) -> dict[str, Any] | None:
    if record is None:
        return None
    result = dict(record)
    if language == "hr":
        for field in fields:
            translated = result.get(f"{field}_hr")
            if translated:
                result[field] = translated
    return result


def public_context(request: Request, **extra: Any) -> dict[str, Any]:
    language = current_language(request)
    theme = request.session.get("theme", "retro")
    if theme not in {"retro", "retro-light"}:
        theme = "retro"
    section_records = rows("SELECT * FROM sections WHERE is_builtin = 0 ORDER BY title COLLATE NOCASE")
    all_sections = {section["id"]: localized(section, ("title",), language) for section in section_records}
    about_record = row("SELECT id FROM sections WHERE slug = 'about' AND is_builtin = 1")
    about_id = about_record["id"] if about_record else None
    def section_tree(section: sqlite3.Row | dict[str, Any], ancestors: frozenset[int] = frozenset()) -> dict[str, Any]:
        section_id = int(section["id"])
        localized_section = all_sections[section_id]
        if section_id in ancestors:
            localized_section["children"] = []
            localized_section["projects"] = []
            return localized_section
        next_ancestors = ancestors | {section_id}
        localized_section["children"] = [
            section_tree(child, next_ancestors)
            for child in section_records
            if child["parent_id"] == section_id
        ]
        localized_section["projects"] = [
            localized(project, ("title", "summary", "body", "category_name"), language)
            for project in projects_for_section(section_id)
        ]
        localized_section["is_dropdown"] = bool(section["is_dropdown"])
        return localized_section

    top_sections = [
        section_tree(section)
        for section in section_records
        if section["parent_id"] is None and section["parent_category_id"] is None
    ]
    return {
        "request": request,
        "language": language,
        "theme": theme,
        "site_copy": get_site_copy(language),
        "sections": top_sections,
        **extra,
    }


def get_site_copy(language: str) -> dict[str, str]:
    copy_rows = rows("SELECT key, text_en, text_hr FROM site_copy")
    return {
        item["key"]: (item["text_hr"] or item["text_en"]) if language == "hr" else item["text_en"]
        for item in copy_rows
    }


def site_copy_value(key: str, language: str) -> str:
    copy = row("SELECT text_en, text_hr FROM site_copy WHERE key = ?", (key,))
    if copy is None:
        return ""
    return (copy["text_hr"] or copy["text_en"]) if language == "hr" else copy["text_en"]


def render(request: Request, template: str, **extra: Any) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=public_context(request, **extra),
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    return render(request, "settings.html", page_title="Settings")


@app.post("/settings/theme")
async def save_theme(request: Request) -> RedirectResponse:
    form = await request.form()
    theme = str(form.get("theme", "retro"))
    request.session["theme"] = theme if theme in {"retro", "retro-light"} else "retro"
    return RedirectResponse("/settings", status_code=303)


def is_admin(request: Request) -> bool:
    return request.session.get("admin") is True


def admin_redirect(request: Request) -> RedirectResponse | None:
    if not is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return None


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return token


def valid_csrf(request: Request, submitted: str) -> bool:
    expected = request.session.get("csrf", "")
    return bool(expected) and secrets.compare_digest(expected, submitted)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def admin_credentials() -> sqlite3.Row | None:
    return row("SELECT username, password_hash FROM admin_credentials WHERE id = 1")


async def save_project_image(upload: UploadFile | None) -> str | None:
    if not isinstance(upload, UploadFile) or not upload.filename:
        return None
    contents = await upload.read(5 * 1024 * 1024 + 1)
    if len(contents) > 5 * 1024 * 1024:
        raise ValueError("image_too_large")
    try:
        with Image.open(io.BytesIO(contents)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("unsupported_image")
            if image.width * image.height > 30_000_000:
                raise ValueError("image_dimensions_too_large")
            image.verify()
        with Image.open(io.BytesIO(contents)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            filename = f"{uuid.uuid4().hex}.webp"
            image.save(UPLOAD_DIRECTORY / filename, format="WEBP", quality=84, method=6)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("invalid_image") from error
    return f"/uploads/{filename}"


async def save_project_images(uploads: list[UploadFile]) -> list[str]:
    image_paths = []
    for upload in uploads:
        image_path = await save_project_image(upload)
        if image_path:
            image_paths.append(image_path)
    return image_paths


def delete_project_image(image_path: str | None) -> None:
    if not image_path:
        return
    filename = Path(image_path).name
    if re.fullmatch(r"[0-9a-f]{32}\.webp", filename):
        (UPLOAD_DIRECTORY / filename).unlink(missing_ok=True)


@app.get("/language/{language}")
def set_language(request: Request, language: str, next: str = "/") -> RedirectResponse:
    if language not in LANGUAGES:
        return RedirectResponse("/", status_code=303)
    request.session["language"] = language
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    return RedirectResponse(next, status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    projects = project_query(limit=10)
    language = current_language(request)
    projects = [localized(project, ("title", "summary", "body", "category_name"), language) for project in projects]
    return render(request, "home.html", projects=projects)


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/projects", response_class=HTMLResponse)
def project_index(request: Request) -> HTMLResponse:
    projects = project_query()
    language = current_language(request)
    projects = [localized(project, ("title", "summary", "body", "category_name"), language) for project in projects]
    return render(request, "projects.html", projects=projects, page_title=site_copy_value("all_projects_label", language))


@app.get("/search", response_class=HTMLResponse)
def search_projects(request: Request, q: str = "") -> HTMLResponse:
    query = q.strip()
    language = current_language(request)
    category_search = query.startswith("/")
    term = query[1:].strip() if category_search else query
    if not term:
        matches = []
    elif category_search:
        pattern = f"%{term}%"
        matches = project_query(
            "projects.id IN (SELECT pc.project_id FROM project_categories AS pc JOIN categories AS c ON c.id = pc.category_id WHERE c.name LIKE ? OR c.name_hr LIKE ? OR c.slug LIKE ?)",
            (pattern, pattern, f"%{term.lower()}%"),
        )
    else:
        pattern = f"%{term}%"
        matches = project_query(
            "projects.title LIKE ? OR projects.title_hr LIKE ? OR projects.summary LIKE ? OR projects.summary_hr LIKE ? OR projects.body LIKE ? OR projects.body_hr LIKE ?",
            (pattern, pattern, pattern, pattern, pattern, pattern),
        )
    matches = [localized(project, ("title", "summary", "body", "category_name"), language) for project in matches]
    label = site_copy_value("search_category" if category_search else "search_text", language)
    return render(
        request,
        "projects.html",
        projects=matches,
        page_title=f"{label}: {term}" if term else label,
        search_query=query,
        search_empty=not matches,
        search_mode="category" if category_search else "text",
    )


@app.get("/category/{slug}", response_class=HTMLResponse)
def category_page(request: Request, slug: str) -> RedirectResponse:
    return RedirectResponse("/projects", status_code=303)


@app.get("/project/{slug}", response_class=HTMLResponse)
def project_detail(request: Request, slug: str) -> HTMLResponse:
    project = next(iter(project_query("projects.slug = ?", (slug,))), None)
    if project is None:
        response = render(request, "not_found.html", page_title="Project not found")
        response.status_code = 404
        return response
    project = localized(project, ("title", "summary", "body", "category_name"), current_language(request))
    gallery_images = rows(
        "SELECT image_path FROM project_images WHERE project_id = ? ORDER BY position, id",
        (project["id"],),
    )
    return render(request, "project.html", project=project, gallery_images=gallery_images)


@app.get("/about", response_class=HTMLResponse)
def about(request: Request) -> HTMLResponse:
    section = row("SELECT * FROM sections WHERE slug = 'about'")
    language = current_language(request)
    section = localized(section, ("title", "body"), language)
    projects = [localized(project, ("title", "summary", "body", "category_name"), language) for project in projects_for_section(section["id"])]
    return render(request, "section.html", section=section, projects=projects, page_title=section["title"])


@app.get("/section/{slug}", response_class=HTMLResponse)
def custom_section(request: Request, slug: str) -> HTMLResponse:
    section = row("SELECT * FROM sections WHERE slug = ?", (slug,))
    if section is None:
        response = render(request, "not_found.html", page_title="Page not found")
        response.status_code = 404
        return response
    section = localized(section, ("title", "body"), current_language(request))
    language = current_language(request)
    projects = [localized(project, ("title", "summary", "body", "category_name"), language) for project in projects_for_section(section["id"])]
    return render(request, "section.html", section=section, projects=projects, page_title=section["title"])


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, saved: int = 0) -> HTMLResponse:
    if not is_admin(request):
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={
                "request": request,
                "csrf": csrf_token(request),
                "error": request.query_params.get("error"),
                "configured": bool(os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD")),
            },
        )
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "request": request,
            "csrf": csrf_token(request),
            "saved": saved,
            "projects": project_query(),
            "project_categories": {
                project["id"]: [item["category_id"] for item in rows(
                    "SELECT category_id FROM project_categories WHERE project_id = ?",
                    (project["id"],),
                )]
                for project in rows("SELECT id FROM projects")
            },
            "project_sections": {
                project["id"]: [item["section_id"] for item in rows(
                    "SELECT section_id FROM project_sections WHERE project_id = ?",
                    (project["id"],),
                )]
                for project in rows("SELECT id FROM projects")
            },
            "project_gallery": {
                project["id"]: rows(
                    "SELECT id, image_path FROM project_images WHERE project_id = ? ORDER BY position, id",
                    (project["id"],),
                )
                for project in rows("SELECT id FROM projects")
            },
            "categories": rows("SELECT * FROM categories ORDER BY name COLLATE NOCASE"),
            "sections": rows(
                """SELECT sections.*, parent.title AS parent_title
                   FROM sections LEFT JOIN sections AS parent ON parent.id = sections.parent_id
                   ORDER BY sections.is_builtin DESC, sections.title COLLATE NOCASE"""
            ),
            "section_parents": rows(
                "SELECT * FROM sections WHERE is_builtin = 1 OR (parent_id IS NULL AND parent_category_id IS NULL) ORDER BY is_builtin DESC, title COLLATE NOCASE"
            ),
            "admin_username": os.getenv("ADMIN_USERNAME", ""),
        },
    )


@app.get("/admin/site-text", response_class=HTMLResponse)
def admin_site_text(request: Request, saved: int = 0) -> HTMLResponse:
    if denied := admin_redirect(request):
        return denied
    return templates.TemplateResponse(
        request=request,
        name="admin_site_text.html",
        context={
            "request": request,
            "csrf": csrf_token(request),
            "saved": saved,
            "copy_fields": rows("SELECT * FROM site_copy ORDER BY key"),
        },
    )


@app.get("/admin/sections/structure")
def admin_section_structure(request: Request) -> JSONResponse:
    if not is_admin(request):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    parents = rows("SELECT id, title, title_hr, is_builtin, parent_id, is_dropdown FROM sections ORDER BY is_builtin DESC, title COLLATE NOCASE")
    parents_by_id = {parent["id"]: dict(parent) for parent in parents}
    for parent in parents_by_id.values():
        path_parts = [parent["title"]]
        current_parent = parent["parent_id"]
        visited = {parent["id"]}
        while current_parent in parents_by_id and current_parent not in visited:
            visited.add(current_parent)
            current = parents_by_id[current_parent]
            path_parts.insert(0, current["title"])
            current_parent = current["parent_id"]
        parent["path"] = " / ".join(path_parts)
    section_records = rows(
        """SELECT sections.id, sections.parent_id, sections.parent_category_id, sections.is_dropdown,
                  EXISTS(SELECT 1 FROM sections AS child WHERE child.parent_id = sections.id) AS has_children
           FROM sections WHERE sections.is_builtin = 0"""
    )
    parent_options = [
        {"value": f"page:{parent['id']}", "title": parent["title"], "title_hr": parent["title_hr"], "path": parent["path"], "kind": "page", "is_builtin": bool(parent["is_builtin"])}
        for parent in parents_by_id.values()
    ]
    return JSONResponse({
        "parents": parent_options,
        "sections": {
            str(section["id"]): {
                "parent_id": section["parent_id"],
                "parent_category_id": section["parent_category_id"],
                "has_children": bool(section["has_children"]),
                "is_dropdown": bool(section["is_dropdown"]),
            }
            for section in section_records
        },
    })


@app.get("/admin/projects/structure")
def admin_project_structure(request: Request) -> JSONResponse:
    if not is_admin(request):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    categories = rows("SELECT id, name, name_hr FROM categories ORDER BY name COLLATE NOCASE")
    sections = rows("SELECT id, title, title_hr, is_builtin, parent_id FROM sections ORDER BY is_builtin DESC, title COLLATE NOCASE")
    section_by_id = {item["id"]: dict(item) for item in sections}
    for item in section_by_id.values():
        path_parts = [item["title"]]
        current_parent = item["parent_id"]
        visited = {item["id"]}
        while current_parent in section_by_id and current_parent not in visited:
            visited.add(current_parent)
            parent = section_by_id[current_parent]
            path_parts.insert(0, parent["title"])
            current_parent = parent["parent_id"]
        item["path"] = " / ".join(path_parts)
    return JSONResponse({
        "categories": [dict(item) for item in categories],
        "sections": list(section_by_id.values()),
        "project_categories": {
            str(project["id"]): [item["category_id"] for item in rows(
                "SELECT category_id FROM project_categories WHERE project_id = ?", (project["id"],)
            )]
            for project in rows("SELECT id FROM projects")
        },
        "project_sections": {
            str(project["id"]): [item["section_id"] for item in rows(
                "SELECT section_id FROM project_sections WHERE project_id = ?", (project["id"],)
            )]
            for project in rows("SELECT id FROM projects")
        },
    })


@app.post("/admin/site-text/save")
async def save_admin_site_text(request: Request) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin/site-text?error=session", status_code=303)
    with closing(connect()) as db:
        for key, _, _, _ in SITE_COPY_DEFAULTS:
            english = form.get(f"en__{key}")
            croatian = form.get(f"hr__{key}")
            if english is not None and croatian is not None:
                db.execute(
                    "UPDATE site_copy SET text_en = ?, text_hr = ? WHERE key = ?",
                    (str(english).strip(), str(croatian).strip(), key),
                )
        db.commit()
    return RedirectResponse("/admin/site-text?saved=1", status_code=303)


@app.post("/admin/login")
async def admin_login(request: Request) -> RedirectResponse:
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin?error=session", status_code=303)
    username = os.getenv("ADMIN_USERNAME", "")
    password = os.getenv("ADMIN_PASSWORD", "")
    supplied_user = str(form.get("username", ""))
    supplied_password = str(form.get("password", ""))
    if username and password and secrets.compare_digest(supplied_user, username) and secrets.compare_digest(supplied_password, password):
        request.session.clear()
        request.session["admin"] = True
        csrf_token(request)
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse("/admin?error=credentials", status_code=303)


@app.post("/admin/password")
async def change_admin_password(request: Request) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin?error=session", status_code=303)
    new_password = str(form.get("new_password", ""))
    confirm_password = str(form.get("confirm_password", ""))
    if len(new_password) < 8 or new_password != confirm_password:
        return RedirectResponse("/admin?error=password", status_code=303)
    with closing(connect()) as db:
        db.execute("UPDATE admin_credentials SET password_hash = ? WHERE id = 1", (hash_password(new_password),))
        db.commit()
    return RedirectResponse("/admin?saved=1&message=password", status_code=303)


@app.post("/admin/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    form = await request.form()
    if valid_csrf(request, str(form.get("csrf", ""))):
        request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.post("/admin/projects/save")
async def save_project(request: Request) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin?error=session", status_code=303)
    title = str(form.get("title", "")).strip()
    summary = str(form.get("summary", "")).strip()
    if not title or not summary:
        return RedirectResponse("/admin?error=project", status_code=303)
    project_id = int(form["project_id"]) if form.get("project_id") else None
    category_ids = {int(value) for value in form.getlist("category_ids") if str(value).isdigit()}
    legacy_category_id = str(form.get("category_id", "")).strip()
    if not category_ids and legacy_category_id.isdigit():
        category_ids.add(int(legacy_category_id))
    section_ids = {int(value) for value in form.getlist("section_ids") if str(value).isdigit()}
    category_ids.intersection_update(int(item["id"]) for item in rows("SELECT id FROM categories"))
    section_ids.intersection_update(int(item["id"]) for item in rows("SELECT id FROM sections"))
    old_project = row("SELECT image_path FROM projects WHERE id = ?", (project_id,)) if project_id else None
    old_image_path = old_project["image_path"] if old_project else ""
    try:
        new_image_path = await save_project_image(form.get("image"))
        new_gallery_paths = await save_project_images(form.getlist("gallery_images"))
    except ValueError as error:
        return RedirectResponse(f"/admin?error={error}", status_code=303)
    if new_image_path:
        image_path = new_image_path
    elif form.get("remove_image") == "on":
        image_path = ""
    else:
        image_path = old_image_path
    values = (
        title,
        unique_slug(str(form.get("slug", "")).strip() or title, "projects", project_id),
        summary,
        str(form.get("title_hr", "")).strip(),
        str(form.get("summary_hr", "")).strip(),
        str(form.get("body", "")).strip(),
        str(form.get("body_hr", "")).strip(),
        str(form.get("link", "")).strip(),
        image_path,
        None,
    )
    with closing(connect()) as db:
        if project_id:
            db.execute(
                "UPDATE projects SET title=?, slug=?, summary=?, title_hr=?, summary_hr=?, body=?, body_hr=?, link=?, image_path=?, category_id=? WHERE id=?",
                (*values, project_id),
            )
        else:
            db.execute(
                "INSERT INTO projects (title, slug, summary, title_hr, summary_hr, body, body_hr, link, image_path, category_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            project_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("DELETE FROM project_categories WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM project_sections WHERE project_id = ?", (project_id,))
        db.executemany(
            "INSERT OR IGNORE INTO project_categories (project_id, category_id) VALUES (?, ?)",
            [(project_id, category_id) for category_id in sorted(category_ids)],
        )
        db.executemany(
            "INSERT OR IGNORE INTO project_sections (project_id, section_id) VALUES (?, ?)",
            [(project_id, section_id) for section_id in sorted(section_ids)],
        )
        existing_gallery = list(db.execute(
            "SELECT id, image_path FROM project_images WHERE project_id = ? ORDER BY position, id",
            (project_id,),
        ).fetchall())
        remove_ids = {int(value) for value in form.getlist("remove_gallery_image") if str(value).isdigit()}
        removed_gallery_paths = [image["image_path"] for image in existing_gallery if image["id"] in remove_ids]
        if remove_ids:
            db.executemany(
                "DELETE FROM project_images WHERE id = ? AND project_id = ?",
                [(image_id, project_id) for image_id in remove_ids],
            )
        next_position = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM project_images WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        db.executemany(
            "INSERT INTO project_images (project_id, image_path, position) VALUES (?, ?, ?)",
            [(project_id, path, next_position + offset) for offset, path in enumerate(new_gallery_paths)],
        )
        db.commit()
    for removed_path in removed_gallery_paths:
        delete_project_image(removed_path)
    if old_image_path and old_image_path != image_path:
        delete_project_image(old_image_path)
    return RedirectResponse("/admin?saved=1", status_code=303)


@app.post("/admin/projects/{project_id}/gallery")
async def update_project_gallery(request: Request, project_id: int) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin?error=session", status_code=303)
    if row("SELECT id FROM projects WHERE id = ?", (project_id,)) is None:
        return RedirectResponse("/admin?saved=1", status_code=303)
    try:
        new_paths = await save_project_images(form.getlist("gallery_images"))
    except ValueError as error:
        return RedirectResponse(f"/admin?error={error}", status_code=303)
    remove_ids = {int(value) for value in form.getlist("remove_gallery_image") if str(value).isdigit()}
    removed_paths = []
    with closing(connect()) as db:
        if remove_ids:
            placeholders = ",".join("?" for _ in remove_ids)
            removed_paths = [
                image["image_path"] for image in db.execute(
                    f"SELECT image_path FROM project_images WHERE project_id = ? AND id IN ({placeholders})",
                    (project_id, *remove_ids),
                ).fetchall()
            ]
            db.execute(
                f"DELETE FROM project_images WHERE project_id = ? AND id IN ({placeholders})",
                (project_id, *remove_ids),
            )
        next_position = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM project_images WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        db.executemany(
            "INSERT INTO project_images (project_id, image_path, position) VALUES (?, ?, ?)",
            [(project_id, path, next_position + offset) for offset, path in enumerate(new_paths)],
        )
        db.commit()
    for image_path in removed_paths:
        delete_project_image(image_path)
    return RedirectResponse("/admin?saved=1", status_code=303)


@app.post("/admin/projects/{project_id}/delete")
async def delete_project(request: Request, project_id: int) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if valid_csrf(request, str(form.get("csrf", ""))):
        project = row("SELECT image_path FROM projects WHERE id = ?", (project_id,))
        gallery_images = rows("SELECT image_path FROM project_images WHERE project_id = ?", (project_id,))
        with closing(connect()) as db:
            db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            db.commit()
        if project:
            delete_project_image(project["image_path"])
        for image in gallery_images:
            delete_project_image(image["image_path"])
    return RedirectResponse("/admin?saved=1", status_code=303)


@app.post("/admin/categories/save")
async def save_category(request: Request) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin?error=session", status_code=303)
    name = str(form.get("name", "")).strip()
    name_hr = str(form.get("name_hr", "")).strip()
    if name:
        with closing(connect()) as db:
            db.execute("INSERT OR IGNORE INTO categories (name, slug, name_hr) VALUES (?, ?, ?)", (name, unique_slug(name, "categories"), name_hr))
            db.commit()
    return RedirectResponse("/admin?saved=1", status_code=303)


@app.post("/admin/categories/{category_id}/delete")
async def delete_category(request: Request, category_id: int) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if valid_csrf(request, str(form.get("csrf", ""))):
        with closing(connect()) as db:
            db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            db.commit()
    return RedirectResponse("/admin?saved=1", status_code=303)


@app.post("/admin/sections/save")
async def save_section(request: Request) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if not valid_csrf(request, str(form.get("csrf", ""))):
        return RedirectResponse("/admin?error=session", status_code=303)
    title = str(form.get("title", "")).strip()
    title_hr = str(form.get("title_hr", "")).strip()
    body = str(form.get("body", "")).strip()
    body_hr = str(form.get("body_hr", "")).strip()
    section_id = int(form["section_id"]) if form.get("section_id") else None
    parent_value = str(form.get("parent_target", form.get("parent_id", ""))).strip()
    parent_id = None
    parent_category_id = None
    if parent_value.startswith("page:"):
        parent_value = parent_value.removeprefix("page:")
    elif parent_value.startswith("category:"):
        return RedirectResponse("/admin?error=parent", status_code=303)
    parent_id = int(parent_value) if parent_value.isdigit() else None
    if parent_id is not None:
        parent = row("SELECT id FROM sections WHERE id = ?", (parent_id,))
        if parent is None or parent_id == section_id:
            return RedirectResponse("/admin?error=parent", status_code=303)
        if section_id:
            descendants = set()
            pending = [section_id]
            while pending:
                current_id = pending.pop()
                if current_id in descendants:
                    continue
                descendants.add(current_id)
                pending.extend(item["id"] for item in rows("SELECT id FROM sections WHERE parent_id = ?", (current_id,)))
            if parent_id in descendants:
                return RedirectResponse("/admin?error=parent", status_code=303)
    submenu_only = str(form.get("is_dropdown", "")) == "on"
    dropdown_enabled = submenu_only
    if title and (body or submenu_only):
        with closing(connect()) as db:
            if section_id:
                db.execute("UPDATE sections SET title = ?, title_hr = ?, body = ?, body_hr = ?, parent_id = ?, parent_category_id = NULL, is_dropdown = ? WHERE id = ?", (title, title_hr, body, body_hr, parent_id, int(dropdown_enabled), section_id))
            else:
                slug = unique_slug(str(form.get("slug", "")).strip() or title, "sections")
                db.execute("INSERT INTO sections (title, slug, body, title_hr, body_hr, parent_id, parent_category_id, is_dropdown) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)", (title, slug, body if not submenu_only else "", title_hr, body_hr if not submenu_only else "", parent_id, int(dropdown_enabled)))
            db.commit()
    return RedirectResponse("/admin?saved=1", status_code=303)


@app.post("/admin/sections/{section_id}/delete")
async def delete_section(request: Request, section_id: int) -> RedirectResponse:
    if denied := admin_redirect(request):
        return denied
    form = await request.form()
    if valid_csrf(request, str(form.get("csrf", ""))):
        with closing(connect()) as db:
            db.execute("DELETE FROM sections WHERE id = ? AND is_builtin = 0", (section_id,))
            db.commit()
    return RedirectResponse("/admin?saved=1", status_code=303)
