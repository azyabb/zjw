# 视觉重构：重新组织模型类结构、调整字段顺序、重命名别名
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime


# Account-related data models
class AccountBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3)


class AccountRegistration(AccountBase):
    password: str = Field(..., min_length=6)


class AccountProfile(AccountBase):
    id: str
    created_at: datetime = Field(alias="createdAt")

    class Config:
        populate_by_name = True


class AccountInDatabase(AccountBase):
    hashed_password: str
    created_at: datetime
    id: str


# Authentication data models
class AuthenticationToken(BaseModel):
    user: AccountProfile
    token: str


class CredentialsInput(BaseModel):
    password: str
    email: EmailStr


# Content (Media) data models
class ContentMetadata(BaseModel):
    tags: Optional[List[str]] = None
    description: Optional[str] = Field(None, max_length=500)


class ContentCreation(ContentMetadata):
    pass


class ContentModification(ContentMetadata):
    pass


class ContentRecord(ContentMetadata):
    user_id: str = Field(alias="userId")
    original_file_name: str = Field(alias="originalFileName")
    file_name: str = Field(alias="fileName")
    id: str
    file_size: int = Field(alias="fileSize")
    media_type: str = Field(alias="mediaType")
    blob_url: str = Field(alias="blobUrl")
    mime_type: str = Field(alias="mimeType")
    uploaded_at: datetime = Field(alias="uploadedAt")
    thumbnail_url: Optional[str] = Field(None, alias="thumbnailUrl")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True


class ContentInDatabase(BaseModel):
    tags: Optional[List[str]] = None
    user_id: str
    description: Optional[str] = None
    file_name: str
    id: str
    original_file_name: str
    blob_url: str
    file_size: int
    media_type: str
    mime_type: str
    thumbnail_url: Optional[str] = None
    uploaded_at: datetime
    updated_at: datetime


class ContentCollection(BaseModel):
    page_size: int = Field(alias="pageSize")
    items: List[ContentRecord]
    total: int
    page: int

    class Config:
        populate_by_name = True


# Error response models
class ErrorInfo(BaseModel):
    message: str
    code: str
    details: Optional[str] = None


class ErrorPayload(BaseModel):
    error: ErrorInfo
