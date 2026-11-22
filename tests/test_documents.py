
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from backend.db import Database
from backend.documents import document_root, fetch_resume, safe_path, store_version, unpack_template


class DocumentTests(unittest.TestCase):
    def test_source_edit_creates_an_immutable_archive_with_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = SimpleNamespace(data_dir=root, github_token="")
            db = Database(root / "test.sqlite")

            def fixture(source, profile, token):
                (source / "main.tex").write_text("Original bullet", encoding="utf-8")
                (source / "experience.tex").write_text("Original bullet", encoding="utf-8")
                (source / "styles").mkdir()
                (source / "styles/portfolio.sty").write_text("% Fixture style", encoding="utf-8")
                return "f" * 40, "main.tex"

            with patch("backend.documents.fetch_resume", fixture):
                first = store_version(db, settings, "owner", "application")
            previous = db.one("SELECT * FROM documents WHERE id=?", (first,))
            edit = SimpleNamespace(source_file="experience.tex", before="Original bullet", after="Accepted bullet")
            second = store_version(db, settings, "owner", "application", previous, edit)
            with zipfile.ZipFile(document_root(settings, first) / "source.zip") as original:
                self.assertEqual(original.read("main.tex"), b"Original bullet")
            with zipfile.ZipFile(document_root(settings, second) / "source.zip") as revised:
                self.assertEqual(revised.read("experience.tex"), b"Accepted bullet")
                self.assertEqual(revised.read("main.tex"), b"Original bullet")
                self.assertIn("styles/portfolio.sty", revised.namelist())
            records = db.all("SELECT owner,application_id,commit_sha FROM documents")
            self.assertEqual(records, [{"owner": "owner", "application_id": "application", "commit_sha": "f" * 40}] * 2)

    def test_relative_source_paths(self):
        self.assertEqual(str(safe_path("documents/resume.tex")), "documents/resume.tex")
        for name in ("../resume.tex", "/resume.tex", "C:/resume.tex", "documents/../resume.tex"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_path(name)

    def test_wrong_archive_entry_reports_the_actual_filename(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("repo-main/Cover_Letter.tex", "Example")
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "Cover_Letter.tex"):
            unpack_template(Path(temporary), safe_path("cover_letter.tex"), "f" * 40, archive.getvalue())

    def test_github_not_found_points_to_branch_and_private_repo_access(self):
        client = httpx.Client
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        profile = {"resume_repo": "example/private-template", "resume_branch": "main", "resume_entry": "letter.tex"}
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            httpx, "Client", lambda **kwargs: client(transport=transport, **kwargs)
        ), self.assertRaisesRegex(ValueError, "branch 'main'.*GITHUB_TOKEN Contents read access"):
            fetch_resume(Path(temporary), profile, "")
