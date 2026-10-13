from fastapi.testclient import TestClient
from io import BytesIO
import re
import sqlite3
from PIL import Image

from app import main


def test_existing_database_migrates_without_losing_english(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    monkeypatch.setattr(main, "DATABASE_PATH", database_path)
    with sqlite3.connect(database_path) as db:
        db.executescript(
            """
            CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE);
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '',
                category_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE sections (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL DEFAULT '', is_builtin INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO projects (title, slug, summary, body) VALUES ('Legacy title', 'legacy-title', 'Legacy summary', 'Legacy body');
            """
        )

    main.init_db()

    with sqlite3.connect(database_path) as db:
        columns = {record[1] for record in db.execute("PRAGMA table_info(projects)")}
        existing_content = db.execute("SELECT title, summary, body FROM projects WHERE slug = 'legacy-title'").fetchone()
    assert {"title_hr", "summary_hr", "body_hr", "image_path"}.issubset(columns)
    assert existing_content == ("Legacy title", "Legacy summary", "Legacy body")


def test_public_pages_and_hidden_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "test.db")
    with TestClient(main.app) as client:
        home = client.get("/")
        assert home.status_code == 200
        nav = home.text.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
        assert nav.index('href="/"') < nav.index('href="/about"')
        assert "Projects" not in nav
        assert "Selected projects" in home.text
        assert "SYSTEM ONLINE" not in home.text
        assert "VISITOR" not in home.text
        assert 'href="/admin"' not in home.text

        about = client.get("/about")
        assert about.status_code == 200
        assert 'href="/settings"' in about.text
        assert "Settings" in about.text
        assert client.get("/projects").status_code == 200
        assert client.get("/project/missing").status_code == 404

        with main.connect() as db:
            for index in range(12):
                db.execute(
                    "INSERT INTO projects (title, slug, summary) VALUES (?, ?, ?)",
                    (f"Project {index:02d}", f"project-{index:02d}", "Test entry"),
                )
        latest = client.get("/").text
        assert "Project 11" in latest and "Project 02" in latest
        assert "Project 01" not in latest and "Project 00" not in latest

        login = client.get("/admin")
        assert login.status_code == 200
        assert "Admin login" in login.text
        response = client.post("/admin/projects/save", data={}, follow_redirects=False)
        assert response.status_code == 303


def test_admin_can_publish_dynamic_content(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "admin-test.db")
    monkeypatch.setenv("ADMIN_USERNAME", "editor")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    with TestClient(main.app) as client:
        login_page = client.get("/admin")
        assert "Admin credentials are not set yet" not in login_page.text
        csrf = re.search(r'name="csrf" value="([^"]+)"', login_page.text).group(1)
        response = client.post(
            "/admin/login",
            data={"csrf": csrf, "username": "editor", "password": "test-password"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        dashboard = client.get("/admin")
        csrf = re.search(r'name="csrf" value="([^"]+)"', dashboard.text).group(1)
        client.post("/admin/categories/save", data={"csrf": csrf, "name": "Experiments", "name_hr": "Eksperimenti"})
        client.post("/admin/categories/save", data={"csrf": csrf, "name": "Utilities", "name_hr": "Alati"})
        category = main.row("SELECT * FROM categories WHERE slug = 'experiments'")
        utility_category = main.row("SELECT * FROM categories WHERE slug = 'utilities'")
        image_data = BytesIO()
        Image.new("RGB", (12, 8), (40, 120, 80)).save(image_data, format="PNG")
        client.post(
            "/admin/projects/save",
            data={
                "csrf": csrf,
                "title": "Tiny Tool",
                "title_hr": "Mali alat",
                "summary": "A useful little experiment.",
                "summary_hr": "Koristan mali eksperiment.",
                "body": "Built one careful step at a time.",
                "body_hr": "Izrađeno pažljivo, korak po korak.",
                "category_ids": [str(category["id"]), str(utility_category["id"])],
            },
            files={"image": ("cover.png", image_data.getvalue(), "image/png")},
        )
        client.post(
            "/admin/sections/save",
            data={"csrf": csrf, "title": "Notes", "title_hr": "Bilješke", "slug": "notes", "body": "Short field notes.", "body_hr": "Kratke bilješke."},
        )
        client.post(
            "/admin/sections/save",
            data={"csrf": csrf, "title": "Resources", "title_hr": "Resursi", "slug": "resources", "body": "Resource index.", "body_hr": "Popis resursa.", "is_dropdown": "on"},
        )
        resources_id = main.row("SELECT id FROM sections WHERE slug = 'resources'")["id"]
        client.post(
            "/admin/sections/save",
            data={"csrf": csrf, "title": "Manual", "title_hr": "Priručnik", "slug": "manual", "body": "Manual page.", "body_hr": "Stranica priručnika.", "parent_id": str(resources_id), "is_dropdown": "on"},
        )
        project_id = main.row("SELECT id FROM projects WHERE slug = 'tiny-tool'")["id"]
        notes_id = main.row("SELECT id FROM sections WHERE slug = 'notes'")["id"]
        manual_id = main.row("SELECT id FROM sections WHERE slug = 'manual'")["id"]
        client.post(
            "/admin/projects/save",
            data={
                "csrf": csrf,
                "project_id": str(project_id),
                "title": "Tiny Tool",
                "title_hr": "Mali alat",
                "summary": "A useful little experiment.",
                "summary_hr": "Koristan mali eksperiment.",
                "body": "Built one careful step at a time.",
                "body_hr": "Izrađeno pažljivo, korak po korak.",
                "category_ids": [str(category["id"]), str(utility_category["id"])],
                "section_ids": [str(notes_id), str(manual_id)],
            },
        )
        gallery_uploads = []
        for color in ((160, 70, 50), (60, 90, 180)):
            image_buffer = BytesIO()
            Image.new("RGB", (10, 8), color).save(image_buffer, format="PNG")
            gallery_uploads.append(("gallery_images", ("detail.png", image_buffer.getvalue(), "image/png")))
        client.post(
            f"/admin/projects/{project_id}/gallery",
            data={"csrf": csrf},
            files=gallery_uploads,
        )

        home = client.get("/")
        assert "Tiny Tool" in home.text
        projects_menu = home.text.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
        assert 'href="/category/experiments"' not in projects_menu
        assert 'href="/category/utilities"' not in projects_menu
        project = main.row("SELECT image_path FROM projects WHERE slug = 'tiny-tool'")
        assert project["image_path"].startswith("/uploads/")
        assert f'src="{project["image_path"]}"' in home.text
        served_image = client.get(project["image_path"])
        assert served_image.status_code == 200
        assert served_image.headers["content-type"] == "image/webp"
        assert 'href="/section/notes"' in home.text
        assert 'href="/section/resources"' not in home.text
        assert 'href="/section/manual"' not in home.text
        structure = client.get("/admin/sections/structure")
        assert structure.status_code == 200
        assert structure.json()["sections"][str(resources_id)]["has_children"] is True
        assert all(option["kind"] == "page" for option in structure.json()["parents"])
        project_structure = client.get("/admin/projects/structure").json()
        assert set(project_structure["project_categories"][str(project_id)]) == {category["id"], utility_category["id"]}
        assert set(project_structure["project_sections"][str(project_id)]) == {notes_id, manual_id}
        assert "Short field notes." in client.get("/section/notes").text
        assert "Tiny Tool" in client.get("/section/notes").text
        assert "Tiny Tool" in client.get("/section/manual").text
        assert "Manual" in client.get("/section/manual").text
        resources_menu = home.text.split('class="nav-dropdown"', 1)[1].split("</details>", 1)[0]
        assert 'href="/section/manual"' not in resources_menu
        manual_menu = home.text.split("Manual <span", 1)[1].split("</details>", 1)[0]
        assert 'href="/project/tiny-tool"' in manual_menu
        text_results = client.get("/search", params={"q": "careful step"})
        assert "Tiny Tool" in text_results.text
        category_results = client.get("/search", params={"q": "/Experiments"})
        assert "Tiny Tool" in category_results.text
        assert "Category:" in category_results.text
        assert "Built one careful step at a time." in client.get("/project/tiny-tool").text
        project_detail_html = client.get("/project/tiny-tool").text
        assert "data-language-toggle" in project_detail_html
        assert "Experiments, Utilities" in project_detail_html
        gallery_html = client.get("/project/tiny-tool").text
        assert 'aria-label="Project image gallery"' in gallery_html
        assert gallery_html.index("Built one careful step at a time.") < gallery_html.index('class="project-gallery"')
        assert "image-lightbox" in gallery_html and "data-gallery-image" in gallery_html
        assert 'class="project-lead"' not in gallery_html
        gallery_items = main.rows("SELECT id, image_path FROM project_images WHERE project_id = ? ORDER BY position", (project_id,))
        assert len(gallery_items) == 2
        assert gallery_html.index(f'data-gallery-image="{project["image_path"]}"') < gallery_html.index(f'data-gallery-image="{gallery_items[0]["image_path"]}"')
        for gallery_item in gallery_items:
            assert client.get(gallery_item["image_path"]).status_code == 200

        translated_project = client.get("/language/hr?next=/project/tiny-tool")
        assert translated_project.status_code == 200
        assert "Mali alat" in translated_project.text
        assert "Koristan mali eksperiment." in translated_project.text
        assert "Izrađeno pažljivo, korak po korak." in translated_project.text
        assert 'lang="hr"' in translated_project.text
        assert "Eksperimenti" in client.get("/").text
        assert "Odabrani projekti" in client.get("/").text
        assert "Selected work" not in client.get("/").text
        assert "Kratke bilješke." in client.get("/section/notes").text
        gallery_file = main.UPLOAD_DIRECTORY / gallery_items[0]["image_path"].rsplit("/", 1)[-1]
        assert gallery_file.exists()
        client.post(
            f"/admin/projects/{project_id}/gallery",
            data={"csrf": csrf, "remove_gallery_image": str(gallery_items[0]["id"])},
        )
        assert len(main.rows("SELECT id FROM project_images WHERE project_id = ?", (project_id,))) == 1
        assert not gallery_file.exists()

        site_text_page = client.get("/admin/site-text")
        assert site_text_page.status_code == 200
        assert "Homepage heading" in site_text_page.text
        assert "Scrolling footer text" in site_text_page.text
        csrf = re.search(r'name="csrf" value="([^\"]+)"', site_text_page.text).group(1)
        saved_copy = client.post(
            "/admin/site-text/save",
            data={
                "csrf": csrf,
                "en__home_heading": "Lovro's work",
                "hr__home_heading": "Lovrin rad",
                "en__footer_text": "Latest work and experiments",
                "hr__footer_text": "Novi radovi i eksperimenti",
            },
            follow_redirects=False,
        )
        assert saved_copy.status_code == 303
        assert "Lovrin rad" in client.get("/").text
        assert "Novi radovi i eksperimenti" in client.get("/").text
        client.get("/language/en?next=/")
        assert "Lovro&#39;s work" in client.get("/").text or "Lovro's work" in client.get("/").text
        assert "Latest work and experiments" in client.get("/").text
        image_file = main.UPLOAD_DIRECTORY / project["image_path"].rsplit("/", 1)[-1]
        assert image_file.exists()
        client.post(
            "/admin/projects/save",
            data={
                "csrf": csrf,
                "project_id": str(main.row("SELECT id FROM projects WHERE slug = 'tiny-tool'")["id"]),
                "title": "Tiny Tool",
                "summary": "A useful little experiment.",
                "remove_image": "on",
            },
        )
        assert main.row("SELECT image_path FROM projects WHERE slug = 'tiny-tool'")["image_path"] == ""
        assert not image_file.exists()
