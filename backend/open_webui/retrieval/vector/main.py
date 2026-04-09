from pydantic import BaseModel
from typing import Optional, List, Any


class VectorItem(BaseModel):
    id: str
    text: str
    vector: List[float | int]
    metadata: Any


class GetResult(BaseModel):
    ids: Optional[List[List[str]]]
    documents: Optional[List[List[str]]]
    metadatas: Optional[List[List[Any]]]


class SearchResult(GetResult):
    distances: Optional[List[List[float | int]]]


class ImageVectorItem(BaseModel):
    id: str
    image_data: str  # base64-encoded PNG
    vector: List[float | int]
    page_number: int
    metadata: Any


class ImageSearchResult(BaseModel):
    ids: Optional[List[List[str]]]
    image_data: Optional[List[List[str]]]
    distances: Optional[List[List[float | int]]]
    metadatas: Optional[List[List[Any]]]
