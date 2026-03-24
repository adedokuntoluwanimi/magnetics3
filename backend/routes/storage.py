from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.services.container import get_storage_backend

router = APIRouter(prefix="/api/storage", tags=["storage"])

_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "geojson": "application/geo+json",
    "kml": "application/vnd.google-earth.kml+xml",
    "kmz": "application/vnd.google-earth.kmz",
    "zip": "application/zip",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


@router.get("/download")
def download_artifact(
    bucket: str,
    object: str,
    storage=Depends(get_storage_backend),
):
    """Proxy a GCS object download through the API.

    Used as a reliable alternative to signed URLs when the service account
    does not have the iam.serviceAccounts.signBlob permission.
    """
    decoded_object = unquote(object)
    try:
        data = storage.download_bytes(bucket, decoded_object)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc

    file_name = decoded_object.rsplit("/", 1)[-1]
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
