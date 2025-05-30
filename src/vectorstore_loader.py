# src/vectorstore_loader.py

from langchain_chroma import Chroma
from chromadb.config import Settings

def get_vectorstore(embedding_model, persist_path: str = "./chroma_db"):
    return Chroma(
        persist_directory=persist_path,
        embedding_function=embedding_model,
        client_settings=Settings(
            persist_directory=persist_path,
            is_persistent=True,
            anonymized_telemetry=False
        )
    )

# ─── your build_facilities_vectorstore goes here ────────────────────────────────
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import os

def build_facilities_vectorstore(
    embedding_model,
    pdf_dir: str,
    persist_path: str = "./facilities_chroma_db",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
):
    # 1. load PDFs
    raw_docs = []
    for fname in os.listdir(pdf_dir):
        if fname.lower().endswith(".pdf"):
            loader = PyPDFLoader(os.path.join(pdf_dir, fname))
            raw_docs.extend(loader.load())
    # 2. chunk
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    chunks = splitter.split_documents(raw_docs)
    # 3. build or load Chroma
    if os.path.exists(persist_path):
        return Chroma(
            persist_directory=persist_path,
            embedding_function=embedding_model,
            client_settings=Settings(
                persist_directory=persist_path,
                is_persistent=True,
                anonymized_telemetry=False
            )
        )
    vs = Chroma.from_documents(
        chunks,
        embedding_model,
        persist_directory=persist_path,
        client_settings=Settings(
            persist_directory=persist_path,
            is_persistent=True,
            anonymized_telemetry=False
        )
    )
    return vs