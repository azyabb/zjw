from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form, Query
from typing import Optional, List
from models import ContentRecord, ContentModification, ContentCollection
from auth import get_current_user_id
from database import cosmos_db
from storage import blob_storage
from utils import validate_file_type, validate_file_size, generate_thumbnail
from datetime import datetime
import uuid
import json
import logging

media_logger = logging.getLogger(__name__)

router = APIRouter(tags=["Media Management"], prefix="/media")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContentRecord)
async def process_file_upload(
    uploaded_file: UploadFile = File(...),
    file_description: Optional[str] = Form(None),
    file_tags: Optional[str] = Form(None),
    current_user: str = Depends(get_current_user_id)
):
    """Process and store uploaded media file"""
    try:
        # Determine file type
        content_type = validate_file_type(uploaded_file)

        # Check file size constraints
        size_in_bytes = validate_file_size(uploaded_file)

        # Process tags input
        parsed_tags = None
        if file_tags:
            try:
                parsed_tags = json.loads(file_tags)
                if not isinstance(parsed_tags, list):
                    raise ValueError("Tags must be an array")
            except json.JSONDecodeError:
                raise HTTPException(
                    detail="Invalid tags format. Must be a JSON array.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

        # Extract file content
        binary_content = await uploaded_file.read()
        await uploaded_file.seek(0)

        # Store file in blob storage
        stored_name, access_url = blob_storage.upload_file(
            uploaded_file.file, current_user, uploaded_file.filename, uploaded_file.content_type
        )

        # Create thumbnail for image files
        preview_url = None
        if content_type == "image":
            preview_data = generate_thumbnail(binary_content)
            if preview_data:
                try:
                    import io
                    preview_stream = io.BytesIO(preview_data)
                    thumb_name, preview_url = blob_storage.upload_file(
                        preview_stream,
                        current_user,
                        f"thumb_{uploaded_file.filename}",
                        "image/jpeg"
                    )
                except Exception as thumb_error:
                    media_logger.warning(f"Thumbnail creation failed: {thumb_error}")

        # Construct media record
        record_id = str(uuid.uuid4())
        current_time = datetime.utcnow().isoformat()
        media_record = {
            "id": record_id,
            "mediaType": content_type,
            "userId": current_user,
            "originalFileName": uploaded_file.filename,
            "fileName": stored_name,
            "mimeType": uploaded_file.content_type,
            "fileSize": size_in_bytes,
            "description": file_description,
            "blobUrl": access_url,
            "tags": parsed_tags,
            "thumbnailUrl": preview_url,
            "uploadedAt": current_time,
            "updatedAt": current_time
        }

        # Persist media metadata
        persisted_media = cosmos_db.create_media(media_record)

        # Return created resource
        return ContentRecord(**persisted_media)

    except HTTPException:
        raise
    except Exception as upload_error:
        media_logger.error(f"File upload failed: {upload_error}")
        raise HTTPException(
            detail=f"Failed to upload media: {str(upload_error)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.get("/search", status_code=status.HTTP_200_OK, response_model=ContentCollection)
async def find_media_by_query(
    search_term: str = Query(..., min_length=1),
    page_num: int = Query(1, ge=1),
    items_per_page: int = Query(20, ge=1, le=100),
    owner_id: str = Depends(get_current_user_id)
):
    """Search for media files matching query"""
    try:
        results, total_count = cosmos_db.search_media(
            user_id=owner_id, query=search_term, page=page_num, page_size=items_per_page
        )

        media_results = [ContentRecord(**item) for item in results]

        return ContentCollection(
            pageSize=items_per_page, items=media_results, page=page_num, total=total_count
        )

    except Exception as search_error:
        media_logger.error(f"Media search failed: {search_error}")
        raise HTTPException(
            detail="Failed to search media",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.get("", status_code=status.HTTP_200_OK, response_model=ContentCollection)
async def retrieve_media_list(
    page_num: int = Query(1, ge=1),
    items_per_page: int = Query(20, ge=1, le=100),
    content_type: Optional[str] = Query(None, regex="^(image|video)$"),
    owner_id: str = Depends(get_current_user_id)
):
    """Fetch paginated media collection"""
    try:
        results, total_count = cosmos_db.get_user_media(
            user_id=owner_id, page=page_num, page_size=items_per_page, media_type=content_type
        )

        collection = [ContentRecord(**item) for item in results]

        return ContentCollection(
            pageSize=items_per_page, total=total_count, page=page_num, items=collection
        )

    except Exception as retrieval_error:
        media_logger.error(f"Media list retrieval failed: {retrieval_error}")
        raise HTTPException(
            detail="Failed to retrieve media list",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.get("/{media_id}", status_code=status.HTTP_200_OK, response_model=ContentRecord)
async def fetch_media_details(
    media_id: str,
    owner_id: str = Depends(get_current_user_id)
):
    """Retrieve specific media file details"""
    try:
        media_item = cosmos_db.get_media_by_id(media_id, owner_id)

        if not media_item:
            raise HTTPException(
                detail="Media not found", status_code=status.HTTP_404_NOT_FOUND
            )

        # Check ownership permissions
        if media_item["userId"] != owner_id:
            raise HTTPException(
                detail="You don't have permission to access this media",
                status_code=status.HTTP_403_FORBIDDEN
            )

        return ContentRecord(**media_item)

    except HTTPException:
        raise
    except Exception as fetch_error:
        media_logger.error(f"Media retrieval error: {fetch_error}")
        raise HTTPException(
            detail="Failed to retrieve media",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.put("/{media_id}", status_code=status.HTTP_200_OK, response_model=ContentRecord)
async def modify_media_info(
    media_id: str,
    metadata_updates: ContentModification,
    owner_id: str = Depends(get_current_user_id)
):
    """Update media file metadata"""
    try:
        # Retrieve existing media
        existing_media = cosmos_db.get_media_by_id(media_id, owner_id)

        if not existing_media:
            raise HTTPException(
                detail="Media not found", status_code=status.HTTP_404_NOT_FOUND
            )

        # Validate ownership
        if existing_media["userId"] != owner_id:
            raise HTTPException(
                detail="You don't have permission to update this media",
                status_code=status.HTTP_403_FORBIDDEN
            )

        # Build update payload
        update_payload = {"updatedAt": datetime.utcnow().isoformat()}

        if metadata_updates.description is not None:
            update_payload["description"] = metadata_updates.description

        if metadata_updates.tags is not None:
            update_payload["tags"] = metadata_updates.tags

        # Apply updates to database
        modified_media = cosmos_db.update_media(media_id, owner_id, update_payload)

        return ContentRecord(**modified_media)

    except HTTPException:
        raise
    except ValueError as validation_error:
        raise HTTPException(
            detail=str(validation_error), status_code=status.HTTP_404_NOT_FOUND
        )
    except Exception as update_error:
        media_logger.error(f"Media update failed: {update_error}")
        raise HTTPException(
            detail="Failed to update media",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_media_file(
    media_id: str,
    owner_id: str = Depends(get_current_user_id)
):
    """Delete media file and associated metadata"""
    try:
        # Fetch media record
        media_record = cosmos_db.get_media_by_id(media_id, owner_id)

        if not media_record:
            raise HTTPException(
                detail="Media not found", status_code=status.HTTP_404_NOT_FOUND
            )

        # Validate ownership
        if media_record["userId"] != owner_id:
            raise HTTPException(
                detail="You don't have permission to delete this media",
                status_code=status.HTTP_403_FORBIDDEN
            )

        # Remove from blob storage
        blob_storage.delete_file(media_record["fileName"])

        # Remove thumbnail if available
        if media_record.get("thumbnailUrl"):
            # Calculate thumbnail blob identifier
            try:
                original_filename = media_record["originalFileName"].split("/")[-1]
                thumb_identifier = media_record["fileName"].replace(
                    original_filename,
                    f"thumb_{original_filename}"
                )
                blob_storage.delete_file(thumb_identifier)
            except Exception as thumb_delete_error:
                media_logger.warning(f"Thumbnail deletion failed: {thumb_delete_error}")

        # Remove from database
        cosmos_db.delete_media(media_id, owner_id)

        return None

    except HTTPException:
        raise
    except Exception as deletion_error:
        media_logger.error(f"Media deletion error: {deletion_error}")
        raise HTTPException(
            detail="Failed to delete media",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
