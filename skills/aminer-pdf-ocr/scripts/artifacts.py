"""Safely materialize the PDF OCR result ZIP into the Skill output directory."""
from __future__ import annotations

import json
import posixpath
import zipfile
from pathlib import Path
from typing import Any

MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


class ArtifactError(ValueError):
    pass


def _safe_member(name: str) -> Path:
    normalized = posixpath.normpath(name)
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ArtifactError(f"unsafe ZIP member path: {name}")
    return Path(normalized)


def extract_result(zip_path: Path, output_dir: Path, *, save_images: bool = True) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    with zipfile.ZipFile(zip_path) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        total = sum(info.file_size for info in members)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ArtifactError("PDF OCR ZIP exceeds the uncompressed size limit")
        safe = [(_safe_member(info.filename), info) for info in members]
        md = next((item for path, item in safe if path.suffix.lower() == ".md"), None)
        middle = next((item for path, item in safe if path.name.endswith("_middle.json")), None)
        if md is None:
            raise ArtifactError("PDF OCR ZIP contains no Markdown file")
        result_md = output_dir / "result.md"
        result_md.write_bytes(archive.read(md))
        middle_path = None
        if middle is not None:
            middle_path = output_dir / middle.filename.replace("/", "_").replace("\\", "_")
            middle_path.write_bytes(archive.read(middle))
        image_count = 0
        if save_images:
            images_dir.mkdir(parents=True, exist_ok=True)
            for path, info in safe:
                if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    continue
                target = images_dir / path.name
                target.write_bytes(archive.read(info))
                image_count += 1
    return {"markdown": str(result_md), "middle_json": str(middle_path) if middle_path else None,
            "images_dir": str(images_dir), "images": image_count,
            "zip_members": len(members)}


def write_metadata(path: Path, *, upload: Any, result: Any, artifacts: dict[str, Any]) -> None:
    payload = {"engine": "pdfocr-open-api", "job_id": upload.job_id,
               "upload": {"status": upload.status, "reused": upload.reused, "code": upload.code,
                           "log_id": upload.log_id},
               "result": {"status": result.status, "is_finish": result.is_finish, "code": result.code,
                          "url_expire_seconds": result.url_expire_seconds, "log_id": result.log_id,
                          "error_code": result.error_code, "error_message": result.error_message},
               "artifacts": artifacts}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
