import json
import re
from pathlib import Path
from typing import List
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.vectorstores import Chroma as ChromaImpl

FILTERABLE_METADATA_KEYS = [
    "Position Title",
    "Job Family Group",
    "Job Family",
    "Compensation Grade",
    "Hybrid-Remote Work Classification (Position)",
]

def clean_text(text: str) -> str:
    return re.sub(r'[\ud800-\udfff]', '', text)

def extract_metadata_recursive(data: dict, keys_to_find: List[str]) -> dict:
    found = {}
    def _search(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys_to_find and k not in found:
                    found[k] = v
                _search(v)
        elif isinstance(obj, list):
            for item in obj:
                _search(item)
    _search(data)
    return {k: found.get(k, "") for k in keys_to_find}

def json_to_document(json_data: dict) -> Document:
    metadata = extract_metadata_recursive(json_data, FILTERABLE_METADATA_KEYS)
    content = json_data.get("Summary", json_data.get("Position Summary", ""))

    all_data = json_data.copy()
    all_data.pop("Summary", None)

    metadata["all_data"] = json.dumps(all_data, ensure_ascii=False)

    cleaned_content = clean_text(content)
    return Document(page_content=cleaned_content, metadata=metadata)

def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def build_vectorstore_from_folder(folder_path: str, embedding_model) -> Chroma:
    docs = []
    for json_file in Path(folder_path).glob("*.json"):
        try:
            data = load_json(json_file)
            doc = json_to_document(data)
            docs.append(doc)
        except Exception as e:
            print(f"⚠️ Skipped {json_file}: {e}")
    if not docs:
        raise ValueError("No valid documents found.")
    return ChromaImpl.from_documents(
        docs,
        embedding_model,
        persist_directory="./chroma_db"
    )
