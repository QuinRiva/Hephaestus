#!/usr/bin/env python3
"""Custom Qdrant MCP server using Vertex AI embeddings.

This is a custom MCP server that wraps Qdrant with Vertex AI embeddings
to match Hephaestus's embedding model (gemini-embedding-001, 3072-dim).
"""

import os
import sys
import asyncio
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from fastmcp import FastMCP
from langchain_google_vertexai import VertexAIEmbeddings

# Initialize FastMCP
mcp = FastMCP("Qdrant with Vertex AI Embeddings")

# Configuration from environment
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "hephaestus_agent_memories")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "test-ds-research")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")

# Initialize clients
qdrant_client = QdrantClient(url=QDRANT_URL)
embeddings_client = VertexAIEmbeddings(
    model_name=EMBEDDING_MODEL,
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION
)


async def generate_embedding(text: str) -> List[float]:
    """Generate embedding using Vertex AI."""
    # Limit input length and use async embedding
    truncated_text = text[:8000]
    # VertexAIEmbeddings doesn't have native async, so we run in executor
    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(
        None,
        lambda: embeddings_client.embed_query(truncated_text)
    )
    return embedding


@mcp.tool()
async def qdrant_find(query: str, limit: int = 5) -> str:
    """Search for relevant information in Qdrant using semantic search.

    Args:
        query: Natural language search query
        limit: Maximum number of results to return (default: 5)

    Returns:
        Formatted string with search results including scores and content
    """
    try:
        # Generate embedding for query
        query_embedding = await generate_embedding(query)

        # Search in Qdrant
        results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=limit,
            with_payload=True
        )

        if not results:
            return "No relevant memories found."

        # Format results
        formatted_results = []
        for i, result in enumerate(results, 1):
            payload = result.payload or {}
            content = payload.get("content", payload.get("text", "No content"))
            memory_type = payload.get("memory_type", "unknown")
            score = result.score

            formatted_results.append(
                f"{i}. [Score: {score:.3f}] [{memory_type}]\n   {content[:500]}..."
                if len(content) > 500 else
                f"{i}. [Score: {score:.3f}] [{memory_type}]\n   {content}"
            )

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"Error searching Qdrant: {str(e)}"


@mcp.tool()
async def qdrant_store(content: str, memory_type: str = "discovery", tags: list = None) -> str:
    """Store information in Qdrant for future retrieval.

    Args:
        content: The content to store
        memory_type: Type of memory (error_fix/discovery/decision/learning/warning/codebase_knowledge)
        tags: Optional list of tags for categorization

    Returns:
        Confirmation message with the stored point ID
    """
    import uuid
    from qdrant_client.models import PointStruct

    try:
        # Generate embedding
        embedding = await generate_embedding(content)

        # Create point
        point_id = str(uuid.uuid4())
        point = PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "content": content,
                "memory_type": memory_type,
                "tags": tags or [],
                "created_at": asyncio.get_event_loop().time()
            }
        )

        # Upsert to Qdrant
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=[point]
        )

        return f"✅ Memory stored successfully with ID: {point_id}"

    except Exception as e:
        return f"Error storing in Qdrant: {str(e)}"


@mcp.tool()
async def qdrant_list_collections() -> str:
    """List all collections in Qdrant.

    Returns:
        List of collection names and their point counts
    """
    try:
        collections = qdrant_client.get_collections()
        
        if not collections.collections:
            return "No collections found in Qdrant."

        result = ["Collections in Qdrant:"]
        for collection in collections.collections:
            info = qdrant_client.get_collection(collection.name)
            result.append(f"  - {collection.name}: {info.points_count} points")

        return "\n".join(result)

    except Exception as e:
        return f"Error listing collections: {str(e)}"


@mcp.tool()
async def qdrant_collection_info(collection_name: str = None) -> str:
    """Get detailed information about a Qdrant collection.

    Args:
        collection_name: Name of the collection (defaults to hephaestus_agent_memories)

    Returns:
        Collection details including vector size, point count, and configuration
    """
    try:
        name = collection_name or COLLECTION_NAME
        info = qdrant_client.get_collection(name)
        
        return f"""Collection: {name}
Points: {info.points_count}
Vectors: {info.vectors_count}
Status: {info.status}
Vector Size: {info.config.params.vectors.size if hasattr(info.config.params, 'vectors') else 'N/A'}
Distance: {info.config.params.vectors.distance if hasattr(info.config.params, 'vectors') else 'N/A'}"""

    except Exception as e:
        return f"Error getting collection info: {str(e)}"


if __name__ == "__main__":
    mcp.run()
