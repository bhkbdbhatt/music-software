"""Rendered sample files.

``GET /v1/files/{job_id}/{variant}`` — how a client actually plays or downloads
a generated sample when the API is configured with the local storage backend.

The local backend records ``file://`` URIs, which are paths on the server's
filesystem; the API rewrites those to this route when projecting results (see
``app.api.v1.jobs._public_url``), so ``GeneratedFile.url`` is always fetchable.
Stored HTTPS URLs (S3) are redirected to rather than proxied: the object is
already public and re-streaming it would put the API in the data path for no
reason.

No API key is required, deliberately. A ``<audio>`` element and Howler's XHR
cannot carry the ``X-API-Key`` header, and the ids are 128-bit unguessable —
the same reasoning that keeps recipe reads open. Anything a key should gate
belongs behind a signed URL, not a header a browser cannot send.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from fastapi import APIRouter, HTTPException, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionDep
from app.models.db import GenerationJob
from app.services.storage import content_type_for

log = get_logger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


def _resolve_local(url: str) -> Path | None:
    """Turn a stored ``file://`` URI into a path, confined to the storage root.

    The URL comes from our own storage layer, not from the caller, so traversal
    is not a live threat — but a containment check costs nothing and turns a
    hypothetical bad row into a 404 instead of an arbitrary file read.

    Args:
        url: The stored ``file://`` URI.

    Returns:
        The resolved path, or ``None`` when it is not inside the configured
        storage directory.
    """
    root = Path(settings.local_storage_dir).resolve()
    target = Path(url2pathname(urlparse(url).path)).resolve()
    if not target.is_relative_to(root):
        return None
    return target


@router.get(
    "/{job_id}/{variant}",
    summary="Fetch a rendered sample",
    description=(
        "Serves one variant of a finished job. Local-storage results are read "
        "from disk with the correct audio content type; remote (S3) results "
        "are answered with a 307 redirect to their object URL. Unauthenticated: "
        "browser audio elements cannot send the API key header, and the job id "
        "is a 128-bit random value."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "No such job, no such variant, or the file is gone."
        },
    },
)
async def get_file(
    job_id: str,
    session: SessionDep,
    variant: int = PathParam(
        ge=0,
        description="Zero-based variant index within the job's result set.",
    ),
) -> Response:
    """Serve one rendered variant.

    Args:
        job_id: The job that produced the file.
        variant: Zero-based index of the variant.
        session: Async database session.

    Returns:
        The file itself, or a redirect to it when storage is remote.

    Raises:
        HTTPException: 404 when the job is unknown, the index is out of range,
            the local file is missing, or a local path escapes the storage root.
    """
    job = await session.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown job: {job_id}")
    if variant >= len(job.result_urls):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"job {job_id} has {len(job.result_urls)} file(s); index {variant} is out of range"
            ),
        )

    url = job.result_urls[variant]
    if not url.startswith("file://"):
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    target = _resolve_local(url)
    if target is None:
        log.warning("file_outside_storage_root", job_id=job_id, variant=variant)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file is unavailable")
    if not target.is_file():
        log.warning("file_missing", job_id=job_id, variant=variant, path=str(target))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file is unavailable")

    try:
        media_type = content_type_for(target.suffix)
    except ValueError:
        media_type = "application/octet-stream"

    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name,
        content_disposition_type="inline",
        headers={
            # Howler and Web Audio decode the response body; telling the browser
            # to revalidate lets a repeat play hit the 304 path instead of
            # re-reading the file off disk.
            "Cache-Control": "private, max-age=3600",
        },
    )
