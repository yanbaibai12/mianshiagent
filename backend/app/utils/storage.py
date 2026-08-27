import io
import os
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import get_settings

settings = get_settings()


def ensure_upload_dir():
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


def get_file_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def is_allowed_file(filename: str) -> bool:
    ext = get_file_extension(filename)
    return ext in {".pdf", ".docx"}


def delete_uploaded_file(file_path: str | None) -> None:
    if not file_path:
        return
    try:
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        target = Path(file_path).resolve()
        if target == upload_root or upload_root not in target.parents:
            return
        target.unlink(missing_ok=True)
    except OSError:
        return


def _has_allowed_content(ext: str, content: bytes) -> bool:
    if ext == ".pdf":
        return content.lstrip().startswith(b"%PDF")

    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and "word/document.xml" in names
        except zipfile.BadZipFile:
            return False

    return False


async def save_upload_file(file: UploadFile) -> str:
    ensure_upload_dir()
    ext = get_file_extension(file.filename or "")
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_name)

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="单个文件大小不能超过 10MB")
    if not _has_allowed_content(ext, content):
        raise HTTPException(status_code=400, detail="文件内容与格式不匹配，请上传有效的 PDF 或 DOCX 文件")

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path
