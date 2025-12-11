from sentence_transformers import SentenceTransformer
import sqlite3
import numpy as np
from typing import List, Dict
from devlog.paths import DB_PATH
import json

# Load model once (lazy loading)
_model = None

def get_model():
    """Lazy load the sentence transformer model"""
    global _model
    if _model is None:
        print("Loading embedding model (first time only)...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')  # 80MB, fast
    return _model

def generate_embedding(text: str) -> np.ndarray:
    """Generate embedding for text"""
    model = get_model()
    return model.encode(text)

def store_commit_embedding(commit_id: int, embedding: np.ndarray):
    """Store embedding in database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Store as JSON array
    embedding_json = json.dumps(embedding.tolist())

    c.execute("""
        CREATE TABLE IF NOT EXISTS commit_embeddings (
            commit_id INTEGER PRIMARY KEY,
            embedding TEXT NOT NULL,
            FOREIGN KEY(commit_id) REFERENCES git_commits(id)
        )
    """)

    c.execute("""
        INSERT OR REPLACE INTO commit_embeddings (commit_id, embedding)
        VALUES (?, ?)
    """, (commit_id, embedding_json))

    conn.commit()
    conn.close()

def get_commit_embedding(commit_id: int) -> np.ndarray:
    """Retrieve embedding from database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT embedding FROM commit_embeddings WHERE commit_id = ?", (commit_id,))
    result = c.fetchone()
    conn.close()

    if result:
        return np.array(json.loads(result[0]))
    return None

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors"""
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def semantic_search(query: str, limit: int = 10) -> List[Dict]:
    """
    Search commits using semantic similarity

    Args:
        query: Natural language query
        limit: Maximum results

    Returns:
        List of commits sorted by relevance
    """
    # Generate query embedding
    query_embedding = generate_embedding(query)

    # Get all commit embeddings
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            c.id,
            c.commit_hash,
            c.short_hash,
            c.message,
            c.timestamp,
            r.repo_name,
            ce.embedding
        FROM git_commits c
        JOIN tracked_repos r ON c.repo_id = r.id
        LEFT JOIN commit_embeddings ce ON c.id = ce.commit_id
        WHERE r.active = 1 AND ce.embedding IS NOT NULL
    """)

    commits = []
    for row in c.fetchall():
        commit = dict(row)
        embedding = np.array(json.loads(commit['embedding']))
        similarity = cosine_similarity(query_embedding, embedding)
        commit['similarity'] = similarity
        commits.append(commit)

    conn.close()

    # Sort by similarity
    commits.sort(key=lambda x: x['similarity'], reverse=True)

    return commits[:limit]

def embed_all_commits():
    """Generate embeddings for all commits that don't have them"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get commits without embeddings
    c.execute("""
        SELECT c.id, c.message, GROUP_CONCAT(cc.file_path, ', ') as files
        FROM git_commits c
        LEFT JOIN commit_embeddings ce ON c.id = ce.commit_id
        LEFT JOIN code_changes cc ON c.id = cc.commit_id
        WHERE ce.embedding IS NULL
        GROUP BY c.id
    """)

    commits = c.fetchall()
    conn.close()

    if not commits:
        print("[green]All commits already have embeddings[/]")
        return

    print(f"[yellow]Generating embeddings for {len(commits)} commits...[/]")

    from rich.progress import track

    for commit_id, message, files in track(commits, description="Processing..."):
        # Combine message and file names for better context
        text = f"{message} {files or ''}"
        embedding = generate_embedding(text)
        store_commit_embedding(commit_id, embedding)
        print(f"[green]Embeddings generated[/]")

