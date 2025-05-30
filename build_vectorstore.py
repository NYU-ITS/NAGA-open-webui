from src.llm_client import get_embedding_model
from src.vectorstore_utils import build_vectorstore_from_folder

def build_and_persist_vectorstore():
    embedding_model = get_embedding_model()
    docs_path = "data/Examples/output/"
    print(f"📦 Loading JSON files from: {docs_path}")
    vectorstore = build_vectorstore_from_folder(docs_path, embedding_model)
    print("✅ Done: Vectorstore written to ./chroma_db")

if __name__ == "__main__":
    build_and_persist_vectorstore()
