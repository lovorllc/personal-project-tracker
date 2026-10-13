# Lovro.me

A small personal portfolio with a retro pixel-inspired interface, project archive, editable pages, and a private admin area.

## Run locally

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. The admin login is at `http://127.0.0.1:8000/admin`; there is intentionally no admin link on the public site. Set `COOKIE_SECURE=true` when deploying behind HTTPS. The SQLite database is created at `data/site.db` on first startup. Set `DATABASE_PATH` to use another location.

Local settings are loaded from `.env`, which is ignored by Git. This workspace is configured with `root` / `root` for local development only. Do not use these credentials on a public deployment; configure a unique `ADMIN_USERNAME`, strong `ADMIN_PASSWORD`, and random `SESSION_SECRET` in the deployment environment instead. Environment variables override values from `.env`.

The database starts with an editable About page and no projects or categories. After signing in, create categories, add projects, and add custom pages from the admin screen. Projects can include a short summary, details, category, and an optional external link. Public pages and project/category navigation are generated from that saved content.

Projects accept one cover image and any number of additional gallery images in JPEG, PNG, or WebP format (up to 5 MB each and 30 megapixels). Images are validated and converted to WebP. The cover is used for project-list thumbnails and the project detail lead image; gallery images appear below it on the project page. Add or remove gallery images in the **Project galleries** section of the admin dashboard. Local uploads are stored in `data/uploads`; Docker stores them in the persistent `/data` volume.

## Languages

Visitors can switch between English and Croatian using the floating language button at the bottom-right; it shows the language it will switch to and remembers the choice for the session. Switching languages keeps the current page. The admin dashboard links to **Edit site text**, where shared headings, navigation labels, empty states, scrolling footer text, and other non-project copy can be edited in both languages. Projects, categories, and custom pages have their own paired translation fields. Existing content remains as English; an empty Croatian field falls back to English.

In the project editor, select any number of **Categories** for informational labels, and any number of **Pages** where the project should appear. Categories do not create public navigation links. Page destinations include About and custom top-level/nested pages; assigned projects render on those pages.

## Docker

Docker Compose reads credentials from `.env`. Copy `.env.example` to `.env`, choose your credentials and a random `SESSION_SECRET`, then start the app:

```bash
docker compose up --build -d
```

Open `http://localhost:8000`. Stop it with `docker compose down`; the SQLite database persists in the `portfolio_data` volume. `docker compose down -v` also deletes that database. Do not use the local `root/root` credentials on a publicly reachable server.

## Tests

```bash
pip install -r requirements.txt
pip install pytest httpx
pytest
```

For production, use a strong unique `SESSION_SECRET`, HTTPS, unique admin credentials, and set `COOKIE_SECURE=true`. The Compose service runs as a non-root user, persists SQLite and uploads in the `portfolio_data` volume, exposes `/healthz` for server health checks, and supports changing the host port with `PORT=8000`.
