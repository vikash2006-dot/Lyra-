"""Document upload, listing, deletion and analysis."""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from app.api.deps import get_services, rate_limit
from app.core.errors import ok
from app.schemas import DocumentAnalyzeRequest

router = APIRouter(tags=["documents"])


@router.get("/documents/supported-types")
async def supported_types(request: Request) -> dict:
    services = get_services(request)
    return ok({
        "extensions": services.documents.supported_extensions(),
        "max_bytes": services.config.max_upload_bytes,
    })


@router.post("/documents/upload", status_code=201)
async def upload(request: Request, file: UploadFile = File(...)) -> dict:
    rate_limit(request, "upload")
    services = get_services(request)
    data = await file.read(services.config.max_upload_bytes + 1)
    doc = services.documents.save_upload(file.filename or "", data)
    return ok(doc, "Document uploaded")


@router.get("/documents")
async def list_documents(request: Request) -> dict:
    return ok(get_services(request).documents.list())


@router.get("/documents/{document_id}")
async def get_document(document_id: str, request: Request) -> dict:
    return ok(get_services(request).documents.get(document_id))


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, request: Request) -> dict:
    get_services(request).documents.delete(document_id)
    return ok({"id": document_id}, "Document deleted")


@router.post("/documents/{document_id}/analyze")
async def analyze_document(document_id: str, request: Request, body: DocumentAnalyzeRequest | None = None) -> dict:
    rate_limit(request, "chat")
    body = body or DocumentAnalyzeRequest()
    result = await get_services(request).documents.analyze(
        document_id, body.mode, session_id=body.session_id, question=body.question
    )
    return ok(result, "Analysis complete")
