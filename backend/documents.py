
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .db import now

WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", re.IGNORECASE)


def safe_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", ".."} or not re.fullmatch(r"[\w .+-]+", part)
                                 or part.endswith((" ", ".")) or WINDOWS_DEVICE.fullmatch(part)
                                 for part in path.parts):
        raise ValueError("Unsupported source path")
    if not path.parts:
        raise ValueError("Empty source path")
    return path


def check_github_response(response, missing):
    code = response.status_code
    if code == 429 or (code == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
        raise ValueError("GitHub's request limit was reached. Try again later or configure GITHUB_TOKEN.")
    if code == 401:
        raise ValueError("GitHub rejected GITHUB_TOKEN. Check that the token is valid and has Contents read access.")
    if code == 403:
        raise ValueError("GitHub denied access. Grant GITHUB_TOKEN Contents read access to this repository.")
    if code == 404:
        raise ValueError(missing)
    if response.is_error:
        raise ValueError(f"GitHub returned HTTP {code}. Try importing the template again later.")


def fetch_resume(directory, profile, token):
    import httpx

    repo = profile["resume_repo"]
    entry = safe_path(profile["resume_entry"])
    if not repo or entry.suffix != ".tex":
        raise ValueError("Configure a GitHub repository and LaTeX entry in Settings")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=25, trust_env=False) as client:
        api = f"https://api.github.com/repos/{repo}"
        branch = profile["resume_branch"]
        ref = quote(branch, safe="")
        response = client.get(f"{api}/commits/{ref}", headers=headers)
        check_github_response(response, f"GitHub cannot read {repo} at branch '{branch}'. "
                              "Check the branch and grant GITHUB_TOKEN Contents read access if the repository is private.")
        response.raise_for_status()
        sha = response.json()["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid repository commit")
        redirect = client.get(f"{api}/zipball/{sha}", headers=headers)
        check_github_response(redirect, f"GitHub could not create an archive for {repo}. Check repository access.")
        location = redirect.headers.get("location", "")
        if redirect.status_code != 302 or not location.startswith("https://codeload.github.com/"):
            raise ValueError("GitHub archive unavailable")
        with client.stream("GET", location) as archive:
            check_github_response(archive, "The GitHub archive is unavailable. Try importing the template again.")
            archive.raise_for_status()
            data = bytearray()
            for chunk in archive.iter_bytes():
                data.extend(chunk)
                if len(data) > 30_000_000:
                    raise ValueError("Repository archive too large")
    return unpack_template(directory, entry, sha, data)


def fetch_cover_template(directory, settings):
    repo = settings.cover_letter_repo
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Set the cover-letter repository in Settings → Profile or set COVER_LETTER_REPO in .env.")
    profile = {"resume_repo": repo, "resume_branch": settings.cover_letter_branch,
               "resume_entry": settings.cover_letter_entry}
    if settings.github_token or not shutil.which("gh"):
        return fetch_resume(directory, profile, settings.github_token)
    entry = safe_path(settings.cover_letter_entry)
    def github(path):
        result = subprocess.run(["gh", "api", "--hostname", "github.com", path], capture_output=True,
                                timeout=60, check=False)
        if result.returncode:
            raise ValueError("GitHub access failed. Grant read access to the cover-letter repository.")
        return result.stdout

    ref = quote(settings.cover_letter_branch, safe="")
    sha = json.loads(github(f"repos/{repo}/commits/{ref}"))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid repository commit")
    return unpack_template(directory, entry, sha, github(f"repos/{repo}/zipball/{sha}"))


def unpack_template(directory, entry, sha, data):
    if len(data) > 30_000_000:
        raise ValueError("Repository archive too large")
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        files = bundle.infolist()
        if len(files) > 1000 or sum(file.file_size for file in files) > 60_000_000:
            raise ValueError("Repository archive exceeds extraction limit")
        seen = set()
        latex_files = []
        for file in files:
            parts = file.filename.split("/", 1)
            if file.is_dir() or len(parts) != 2 or any(part.startswith(".") for part in parts[1].split("/")):
                continue
            path = safe_path(parts[1])
            if stat.S_ISLNK(file.external_attr >> 16) or str(path).casefold() in seen:
                raise ValueError("Unsupported repository archive")
            seen.add(str(path).casefold())
            if path.suffix == ".tex":
                latex_files.append(path)
            target = directory.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(file) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    if entry not in latex_files:
        latex_files.sort(key=lambda path: (len(path.parts), path.as_posix()))
        available = ", ".join(path.as_posix() for path in latex_files[:5])
        detail = f" Available LaTeX files include {available}." if available else ""
        raise ValueError(f"LaTeX entry '{entry}' was not found. Check the filename and capitalization." + detail)
    return sha, str(entry)


def document_root(settings, document_id):
    return settings.data_dir / "documents" / document_id


def tex_source(root, name):
    path = root / safe_path(name)
    if path.suffix.lower() != ".tex" or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Choose a LaTeX file from this version")
    return path


SOURCE_TYPES = {".tex", ".cls", ".sty", ".bib", ".bst", ".txt", ".md", ".cfg", ".def"}


def project_source(root, name):
    path = root / safe_path(name)
    if (path.suffix.lower() not in SOURCE_TYPES or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 160000):
        raise ValueError("Select a project text file smaller than 160 KB")
    return path


def apply_edit(path, edit):
    original = path.read_text(encoding="utf-8")
    if original.count(edit.before) != 1:
        raise ValueError("The original text must occur exactly once in the selected file")
    path.write_text(original.replace(edit.before, edit.after, 1), encoding="utf-8")


def store_version(db, settings, owner, app_id, previous=None, edit=None, kind="resume", changes=None, created=(),
                  verified_pdf=None):
    document_id = uuid.uuid4().hex
    root = document_root(settings, document_id)
    source = root / "source"
    source.mkdir(parents=True)
    try:
        if previous:
            kind = previous["kind"]
            shutil.copytree(document_root(settings, previous["id"]) / "source", source, dirs_exist_ok=True)
            sha, entry = previous["commit_sha"], previous["entry"]
            for name, content in (changes or {}).items():
                if len(content.encode("utf-8"))>160000:
                    raise ValueError("Source file exceeds 160 KB")
                if name in created:
                    path=source / safe_path(name)
                    if path.suffix.lower() not in SOURCE_TYPES or not path.resolve().is_relative_to(source.resolve()):
                        raise ValueError("Unsupported source path")
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open("x",encoding="utf-8") as f:
                        f.write(content)
                else:
                    project_source(source, name).write_text(content, encoding="utf-8")
            if edit:
                apply_edit(tex_source(source, getattr(edit, "source_file", None) or entry), edit)
        elif kind == "cover":
            profile=db.settings(owner)
            config=settings.model_copy(update={"cover_letter_repo":profile["cover_repo"],"cover_letter_branch":profile["cover_branch"],
                                              "cover_letter_entry":profile["cover_entry"]}) if profile.get("cover_repo") else settings
            sha, entry = fetch_cover_template(source, config)
        else:
            sha, entry = fetch_resume(source, db.settings(owner), settings.github_token)
        with zipfile.ZipFile(root / "source.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
            for file in source.rglob("*"):
                if file.is_file():
                    bundle.write(file, file.relative_to(source).as_posix())
        if verified_pdf:
            shutil.copyfile(verified_pdf, root / "resume.pdf")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if verified_pdf and conn.execute(
                """SELECT id FROM documents WHERE owner=? AND application_id=? AND kind=?
                   ORDER BY created_at DESC,rowid DESC LIMIT 1""", (owner, app_id, kind)
            ).fetchone()[0] != previous["id"]:
                raise ValueError("A newer version already exists. Review the proposed edits before merging.")
            conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                         (document_id, owner, app_id, sha, entry, now(), bool(verified_pdf), kind))
            if verified_pdf:
                conn.execute("INSERT INTO document_checks VALUES(?,1,0)", (document_id,))
                conn.execute("INSERT INTO prepared_documents VALUES(?)", (document_id,))
            if previous and previous["application_id"]==app_id:
                conn.execute("INSERT INTO document_parents VALUES(?,?)",(document_id,previous["id"]))
    except Exception:
        shutil.rmtree(root)
        raise
    return document_id


def render_pdf(work, entry):
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR") if name in os.environ}
    executable = shutil.which("pdflatex")
    if not executable:
        raise ValueError("Install pdfLaTeX to compile documents")
    env.update({"openin_any": "p", "openout_any": "p", "TEXMFOUTPUT": str(work),
                "TEMP": str(work), "TMP": str(work)})
    for _ in range(2):
        result = subprocess.run(
            [executable, "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode",
             "-jobname=dashboard-resume", "./" + entry.name],
            cwd=work / entry.parent, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=35, check=False,
        )
        if result.returncode:
            log=work/entry.parent/"dashboard-resume.log"
            lines=log.read_text(encoding="utf-8",errors="replace").splitlines() if log.is_file() else []
            detail=next((" ".join(lines[i:i+5])[:450] for i,line in enumerate(lines) if line.startswith("!")),"Check the template and installed packages.")
            raise ValueError("LaTeX compile failed. "+detail)
    return work / entry.parent / "dashboard-resume.pdf"


def preview_edit(settings, document, edit):
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        shutil.copytree(document_root(settings, document["id"]) / "source", work, dirs_exist_ok=True)
        entry = PurePosixPath(document["entry"])
        apply_edit(tex_source(work, edit.source_file or document["entry"]), edit)
        pdf = render_pdf(work, entry)
        if pdf.stat().st_size > 20_000_000:
            raise ValueError("PDF exceeds the preview size limit")
        return pdf.read_bytes()


def cover_letter_pdf(content):
    replacements = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "%": r"\%",
                    "&": r"\&", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    letter = "".join(replacements.get(character, character) for character in content)
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        entry = PurePosixPath("cover-letter.tex")
        (work / entry).write_text(
            "\\documentclass[11pt]{article}\n\\usepackage[margin=1in]{geometry}\n"
            "\\pagestyle{empty}\n\\setlength{\\parindent}{0pt}\n\\setlength{\\parskip}{1em}\n"
            "\\begin{document}\n" + letter + "\n\\end{document}\n", encoding="utf-8",
        )
        return render_pdf(work, entry).read_bytes()


def compile_version(db, settings, document):
    root = document_root(settings, document["id"])
    if document["compiled"]:
        return
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        shutil.copytree(root / "source", work, dirs_exist_ok=True)
        pdf = render_pdf(work, PurePosixPath(document["entry"]))
        pages, overflow = pdf_checks(pdf)
        overfull = len(overflow)
        temporary = root / f"{uuid.uuid4().hex}.tmp"
        shutil.copyfile(pdf, temporary)
        # An existing PDF is immutable, including after concurrent compile requests.
        try:
            os.link(temporary, root / "resume.pdf")
        except FileExistsError:
            pass
        finally:
            temporary.unlink()
    with db.connect() as conn:
        conn.execute("UPDATE documents SET compiled=1 WHERE id=?", (document["id"],))
        conn.execute("INSERT OR IGNORE INTO document_checks VALUES(?,?,?)", (document["id"], pages, overfull))


def pdf_checks(pdf):
    log = pdf.with_suffix(".log")
    lines = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    page_match = re.search(r"Output written on [^(]+\((\d+) pages?[,)]", lines)
    pages = int(page_match[1]) if page_match else None
    overflow = re.findall(r"^Overfull \\[hv]box[^\r\n]*", lines, re.MULTILINE)
    return pages, overflow
