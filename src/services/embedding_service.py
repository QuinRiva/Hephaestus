"""Service for generating and comparing embeddings for task deduplication."""

import numpy as np
import openai
from typing import List, Dict, Any, Optional
import logging
import os
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.core.simple_config import get_config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating and comparing embeddings.
    
    Supports multiple embedding providers:
    - openai: Uses OpenAI's text-embedding models
    - vertex_ai: Uses Google Cloud Vertex AI embeddings
    - google_ai: Uses Google Generative AI embeddings
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        """Initialize the embedding service.

        Args:
            openai_api_key: OpenAI API key (optional if using other providers)
        """
        self.config = get_config()
        self.model = self.config.task_embedding_model
        
        # Determine embedding provider from config
        self.embedding_provider = getattr(self.config, 'embedding_provider', None)
        if not self.embedding_provider:
            # Fallback: infer from model name or default to openai
            if 'gecko' in self.model.lower() or 'text-embedding-0' in self.model.lower():
                self.embedding_provider = 'vertex_ai'
            elif 'gemini' in self.model.lower():
                self.embedding_provider = 'google_ai'
            else:
                self.embedding_provider = 'openai'
        
        logger.info(f"Initializing EmbeddingService with provider: {self.embedding_provider}, model: {self.model}")
        
        self._embedding_model = None
        self._openai_client = None
        
        self._initialize_provider(openai_api_key)

    def _initialize_provider(self, openai_api_key: Optional[str] = None):
        """Initialize the appropriate embedding provider."""
        
        if self.embedding_provider == "openai":
            # Use OpenAI directly
            api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
            if api_key:
                self._openai_client = openai.OpenAI(api_key=api_key)
                logger.info(f"  ✓ Initialized OpenAI embedding client with model: {self.model}")
            else:
                logger.warning("OpenAI API key not provided, embedding generation may fail")
                
        elif self.embedding_provider == "vertex_ai":
            # Use LangChain VertexAIEmbeddings
            try:
                from langchain_google_vertexai import VertexAIEmbeddings
                
                project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
                
                if project_id:
                    # Map gemini-embedding model names to Vertex AI equivalents
                    model_name = self.model
                    if model_name.startswith("gemini-embedding"):
                        # gemini-embedding-001 -> text-embedding-005 (current best for Vertex AI)
                        logger.warning(f"Model '{model_name}' is a Gemini API model. For Vertex AI, using 'text-embedding-005' instead.")
                        model_name = "text-embedding-005"
                    
                    self._embedding_model = VertexAIEmbeddings(
                        model_name=model_name,
                        project=project_id,
                        location=location
                    )
                    logger.info(f"  ✓ Initialized Vertex AI embedding client with model: {model_name} (project: {project_id}, location: {location})")
                else:
                    logger.error("GOOGLE_CLOUD_PROJECT environment variable required for Vertex AI embeddings")
                    
            except ImportError:
                logger.error("langchain_google_vertexai not installed. Run: pip install langchain-google-vertexai")
                
        elif self.embedding_provider == "google_ai":
            # Use LangChain GoogleGenerativeAIEmbeddings (for Gemini API)
            try:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                
                google_key = os.getenv("GOOGLE_API_KEY")
                if google_key:
                    # Format model name for Google AI
                    model_name = self.model
                    if not model_name.startswith("models/"):
                        model_name = f"models/{model_name}"
                    
                    self._embedding_model = GoogleGenerativeAIEmbeddings(
                        model=model_name,
                        google_api_key=google_key
                    )
                    logger.info(f"  ✓ Initialized Google AI embedding client with model: {model_name}")
                else:
                    logger.error("GOOGLE_API_KEY environment variable required for Google AI embeddings")
                    
            except ImportError:
                logger.error("langchain_google_genai not installed. Run: pip install langchain-google-genai")
        else:
            logger.warning(f"Unknown embedding provider: {self.embedding_provider}, falling back to OpenAI")
            api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
            if api_key:
                self._openai_client = openai.OpenAI(api_key=api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(
            (openai.APIError, openai.APIConnectionError, openai.RateLimitError, Exception)
        ),
        reraise=True,
    )
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using the configured provider.

        Retries up to 3 times with exponential backoff for API errors.

        Args:
            text: Text to generate embedding for

        Returns:
            List of floats representing the embedding vector

        Raises:
            Exception: If embedding generation fails after retries
        """
        # Truncate text if too long
        max_chars = 30000
        if len(text) > max_chars:
            logger.warning(f"Text truncated from {len(text)} to {max_chars} characters")
            text = text[:max_chars]

        try:
            if self._embedding_model is not None:
                # Use LangChain embedding model (Vertex AI or Google AI)
                embedding = await self._embedding_model.aembed_query(text[:8000])
                logger.debug(f"Generated embedding with dimension: {len(embedding)} via {self.embedding_provider}")
                return embedding
                
            elif self._openai_client is not None:
                # Use OpenAI client directly
                response = self._openai_client.embeddings.create(
                    model=self.model, input=text, encoding_format="float"
                )
                embedding = response.data[0].embedding
                logger.debug(f"Generated embedding with dimension: {len(embedding)} via OpenAI")
                return embedding
            else:
                logger.error("No embedding provider initialized")
                # Return zero vector as fallback
                dimension = getattr(self.config, 'task_embedding_dimension', 3072)
                return [0.0] * dimension

        except (openai.APIError, openai.APIConnectionError, openai.RateLimitError) as e:
            logger.warning(f"OpenAI API error (will retry): {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to generate embedding via {self.embedding_provider}: {e}")
            raise

    def calculate_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First embedding vector
            vec2: Second embedding vector

        Returns:
            Cosine similarity score between -1 and 1
        """
        # Handle edge cases
        if not vec1 or not vec2:
            logger.warning("Empty vector provided for similarity calculation")
            return 0.0

        if len(vec1) != len(vec2):
            logger.warning(f"Vector dimension mismatch: {len(vec1)} vs {len(vec2)}")
            return 0.0

        try:
            # Convert to numpy arrays for efficient computation
            arr1 = np.array(vec1, dtype=np.float32)
            arr2 = np.array(vec2, dtype=np.float32)

            # Calculate norms
            norm_a = np.linalg.norm(arr1)
            norm_b = np.linalg.norm(arr2)

            # Handle zero vectors
            if norm_a == 0 or norm_b == 0:
                logger.warning("Zero vector provided for similarity calculation")
                return 0.0

            # Calculate cosine similarity
            similarity = np.dot(arr1, arr2) / (norm_a * norm_b)

            # Ensure result is in valid range (floating point errors can cause slight overflow)
            similarity = np.clip(similarity, -1.0, 1.0)

            return float(similarity)

        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0

    def calculate_batch_similarities(
        self, query_embedding: List[float], embeddings: List[List[float]]
    ) -> List[float]:
        """Calculate cosine similarities between a query and multiple embeddings efficiently.

        Args:
            query_embedding: Query embedding vector
            embeddings: List of embedding vectors to compare against

        Returns:
            List of similarity scores
        """
        if not embeddings:
            return []

        try:
            # Convert to numpy arrays
            query_arr = np.array(query_embedding, dtype=np.float32)
            embeddings_arr = np.array(embeddings, dtype=np.float32)

            # Normalize query
            query_norm = np.linalg.norm(query_arr)
            if query_norm == 0:
                return [0.0] * len(embeddings)
            query_normalized = query_arr / query_norm

            # Normalize embeddings
            norms = np.linalg.norm(embeddings_arr, axis=1)
            # Avoid division by zero
            norms[norms == 0] = 1.0
            embeddings_normalized = embeddings_arr / norms[:, np.newaxis]

            # Calculate dot products (cosine similarities)
            similarities = np.dot(embeddings_normalized, query_normalized)

            # Clip to valid range and convert to list
            similarities = np.clip(similarities, -1.0, 1.0)
            return similarities.tolist()

        except Exception as e:
            logger.error(f"Error in batch similarity calculation: {e}")
            # Fallback to individual calculations
            return [self.calculate_cosine_similarity(query_embedding, emb) for emb in embeddings]

    async def generate_ticket_embedding(
        self, title: str, description: str, tags: List[str]
    ) -> List[float]:
        """
        Generate weighted embedding for ticket content.

        Weighting strategy:
        - Title: 2x weight (repeat title twice in input)
        - Description: 1x weight
        - Tags: 1.5x weight (repeat tags approximately 1.5x)

        Args:
            title: Ticket title
            description: Ticket description
            tags: List of tags

        Returns:
            Embedding vector (dimension depends on configured model)
        """
        # Combine with weights
        # Title gets 2x weight, tags get ~1.5x weight
        tag_text = " ".join(tags)
        weighted_text = f"{title} {title} {description} {tag_text} {tag_text}"

        logger.debug(f"Generating weighted ticket embedding (title 2x, tags 1.5x)")
        return await self.generate_embedding(weighted_text)

    async def generate_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for search query.

        Args:
            query: Search query text

        Returns:
            Embedding vector (same dimension as ticket embeddings)
        """
        logger.debug(f"Generating query embedding for: {query[:100]}...")
        return await self.generate_embedding(query)
