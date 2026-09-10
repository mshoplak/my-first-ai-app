import os
import secrets
from pathlib import Path
import openai
from pinecone import Pinecone
from dotenv import load_dotenv

# Load local environment parameter states
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-app-logs")

if not OPENAI_API_KEY or not PINECONE_API_KEY:
    raise RuntimeError("Ingestion Stopped: Missing core API environment tracking keys.")

# Initialize upstream native client sockets
pc = Pinecone(api_key=PINECONE_API_KEY)
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)

SOURCE_FOLDER = Path("./immigration_source_data")
TARGET_NAMESPACE = "global-immigration-statutes"

def chunk_text_by_paragraphs(text: str, max_chars: int = 1500) -> list[str]:
    """Splits raw unstructured layout documents into semantic paragraph chunks."""
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_length = 0
    
    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue
        if current_length + len(p_clean) > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(p_clean)
        current_length += len(p_clean)
        
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks

def run_bulk_ingestion():
    if not SOURCE_FOLDER.exists():
        SOURCE_FOLDER.mkdir()
        print(f"Created '{SOURCE_FOLDER}' folder. Place your raw country immigration text files (.txt) inside and re-run.")
        return

    txt_files = list(SOURCE_FOLDER.glob("*.txt"))
    if not txt_files:
        print(f"No document vectors to process. Place your legal guideline .txt files inside '{SOURCE_FOLDER}'.")
        return

    print(f"Starting vector processing sequence across {len(txt_files)} documentation source assets...")

    for file_path in txt_files:
        doc_id = file_path.stem
        print(f"Reading internal elements for: {doc_id}...")
        
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        text_chunks = chunk_text_by_paragraphs(raw_content)
        print(f"Fragmented text layout into {len(text_chunks)} unique context payloads.")

        vectors_to_upsert = []
        for idx, chunk in enumerate(text_chunks):
            # Compute deep mathematical representation embeddings via text-embedding-3-large
            response = openai_client.embeddings.create(
                input=[chunk],
                model="text-embedding-3-large",
                dimensions=2048
            )
            vector_values = response.data[0].embedding
            unique_vector_id = f"statute_{doc_id}_{idx}_{secrets.token_hex(4)}"

            # Document metadata payload layout
            metadata = {
                "document_id": doc_id,
                "chunk_index": str(idx),
                "text_extract": chunk
            }

            vectors_to_upsert.append({
                "id": unique_vector_id,
                "values": vector_values,
                "metadata": metadata
            })

        # Submit vectors across the secure law namespace pool
        if vectors_to_upsert:
            print(f"Transmitting batch records directly upstream to Pinecone namespace [{TARGET_NAMESPACE}]...")
            index.upsert(vectors=vectors_to_upsert, namespace=TARGET_NAMESPACE)
            print(f"Successfully locked down {len(vectors_to_upsert)} vector vectors for file: {doc_id}")

    print("\nALL IMMIGRATION KNOWLEDGE MATRICES SUCCESSFULLY LOCKED AND LOADED!")

if __name__ == "__main__":
    run_bulk_ingestion()
