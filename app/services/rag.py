# Copyright 2024
# Directory: yt-rag/app/services/rag.py

"""
RAG (Retrieval-Augmented Generation) service implementation.
Orchestrates the complete RAG pipeline: chunk → embed → search → generate.
"""

import logging
import time
import re
from dataclasses import dataclass
from typing import List, Dict, Any
from ..core.database import db
from .embedding import embedding_service
from .chat import ChatUnavailableError, chat_service
from .chunker import chunker
from ..data.default_documents import DEFAULT_DOCUMENTS, DOCUMENT_TITLES

logger = logging.getLogger(__name__)

NO_RESULTS_TEXT = (
    "I don't have enough information to answer your question. "
    "Could you please rephrase or provide more context?"
)
EXTRACTIVE_LEAD = "A generated answer isn't available right now. Here are the most relevant passages:"
RETRIEVAL_ERROR_TEXT = "I couldn't search the knowledge base right now. Please try again shortly."


@dataclass(frozen=True)
class SeedResult:
    """What a seed changed: chunks saved, and old chunks deleted."""
    inserted: int
    removed: int


class RAGService:
    """Main RAG service orchestrating the complete pipeline."""
    
    def __init__(self):
        """Initialize RAG service."""
        self.db = db
        self.embedding_service = embedding_service
        self.chat_service = chat_service
        self.chunker = chunker
    
    async def seed_documents(self, documents: List[Dict[str, str]] = None) -> SeedResult:
        """
        Replace the knowledge base with these documents.

        The new chunks are embedded and saved first; only then is every other chunk
        deleted. If embedding or saving fails, nothing is deleted. If the documents
        produce no chunks, nothing changes and no embeddings are requested.

        Args:
            documents: Optional list of documents. If None, uses default documents.

        Returns:
            How many chunks were saved and how many old chunks were deleted
        """
        start_time = time.time()

        # Use default documents if none provided
        if documents is None:
            documents = DEFAULT_DOCUMENTS
            logger.info("Using default documents for seeding")

        try:
            # Step 1: Chunk documents
            chunks = self.chunker.chunk_documents(documents)
            logger.info(f"Created {len(chunks)} chunks from {len(documents)} documents")
            if not chunks:
                logger.info("The documents produced no chunks; the knowledge base is unchanged")
                return SeedResult(inserted=0, removed=0)

            # Step 2: Generate embeddings for all chunks
            texts = [chunk['text'] for chunk in chunks]
            embeddings = await self.embedding_service.embed_texts(texts)

            # Step 3: Combine chunks with embeddings
            for chunk, embedding in zip(chunks, embeddings):
                chunk['embedding'] = embedding

            # Step 4: Store in database
            inserted_count = await self.db.upsert_chunks(chunks)

            # Step 5: With the new chunks saved, delete every chunk that wasn't seeded
            removed_count = await self.db.delete_chunks_except([chunk['chunk_id'] for chunk in chunks])

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"Seeding completed in {elapsed_ms}ms: {inserted_count} chunks inserted, {removed_count} removed"
            )

            return SeedResult(inserted=inserted_count, removed=removed_count)

        except Exception as e:
            logger.error(f"Seeding failed: {e}")
            raise
    
    async def answer_query(self, query: str, top_k: int = 6) -> Dict[str, Any]:
        """
        Process a query through the complete RAG pipeline.
        
        Args:
            query: User's question
            top_k: Number of chunks to retrieve
            
        Returns:
            Dictionary with answer, citations, sources (the passage and document
            title behind each citation) and debug info. debug.answer_mode
            is "generated", "extractive" (model unavailable, passages returned),
            "no_results" or "error" (failed before the model was called).
        """
        start_time = time.time()

        def result(
            text: str,
            citations: List[str],
            top_doc_ids: List[str],
            answer_mode: str,
            context_blocks: List[Dict[str, Any]] = (),
        ) -> Dict[str, Any]:
            return {
                'text': text,
                'citations': citations,
                'sources': self._sources(citations, context_blocks),
                'debug': {
                    'top_doc_ids': top_doc_ids,
                    'latency_ms': int((time.time() - start_time) * 1000),
                    'answer_mode': answer_mode,
                },
            }

        try:
            # Step 1: Generate query embedding
            query_embedding = await self.embedding_service.embed_query(query)

            # Step 2: Vector similarity search
            search_results = await self.db.vector_search(query_embedding, top_k)

            if not search_results:
                return result(NO_RESULTS_TEXT, [], [], 'no_results')

            # Step 3: Deduplicate and prepare context
            context_blocks = self._prepare_context(search_results)
            context_ids = [block['chunk_id'] for block in context_blocks]

        except Exception as e:
            # No provider text in the response; the type goes to the server log.
            logger.error(f"Query processing failed before answering: {type(e).__name__}")
            return result(RETRIEVAL_ERROR_TEXT, [], [], 'error')

        # Step 4: Generate answer, or fall back to the retrieved passages
        try:
            answer_text = await self.chat_service.generate_answer(query, context_blocks)
        except ChatUnavailableError:
            logger.warning("Chat model unavailable; returning retrieved passages instead")
            return result(
                self._extractive_answer(context_blocks), context_ids, context_ids, 'extractive', context_blocks
            )

        # Step 5: Extract citations from answer
        citations = self._extract_citations(answer_text, context_blocks)
        response = result(answer_text, citations, context_ids, 'generated', context_blocks)
        logger.info(f"Query processed in {response['debug']['latency_ms']}ms with {len(citations)} citations")
        return response

    def _sources(self, citations: List[str], context_blocks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """The passage behind each citation, in citation order, with its document's title.

        The title comes from the default documents by document ID (the chunk ID
        before "#"); a chunk from any other document gets its chunk ID as title.
        """
        blocks = {block['chunk_id']: block for block in context_blocks}
        return [
            {
                'chunk_id': chunk_id,
                'title': DOCUMENT_TITLES.get(chunk_id.split('#')[0], chunk_id),
                'text': blocks[chunk_id].get('text', ''),
            }
            for chunk_id in citations
            if chunk_id in blocks
        ]

    def _extractive_answer(self, context_blocks: List[Dict[str, Any]]) -> str:
        """Answer text built from the retrieved passages, one per paragraph."""
        passages = [f"[{block['chunk_id']}] {block.get('text', '')}" for block in context_blocks]
        return "\n\n".join([EXTRACTIVE_LEAD, *passages])
    
    def _prepare_context(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Prepare context blocks from search results with simple deduplication.
        
        Args:
            search_results: Raw search results from database
            
        Returns:
            Processed context blocks
        """
        # Simple deduplication by chunk_id prefix (MMR-lite)
        seen_prefixes = set()
        context_blocks = []
        
        for result in search_results:
            chunk_id = result.get('chunk_id', '')
            
            # Extract base chunk ID (before #)
            base_id = chunk_id.split('#')[0] if '#' in chunk_id else chunk_id
            
            if base_id not in seen_prefixes:
                context_blocks.append(result)
                seen_prefixes.add(base_id)
            
            # Limit to reasonable context size
            if len(context_blocks) >= 4:
                break
        
        logger.info(f"Prepared {len(context_blocks)} unique context blocks")
        return context_blocks
    
    def _extract_citations(self, answer_text: str, context_blocks: List[Dict[str, Any]]) -> List[str]:
        """
        Extract citation chunk_ids from the generated answer.
        
        Args:
            answer_text: Generated answer text
            context_blocks: Context blocks that were provided
            
        Returns:
            List of chunk_ids that were cited
        """
        # Find all citations in format [chunk_id]
        citation_pattern = r'\[([^\]]+)\]'
        found_citations = re.findall(citation_pattern, answer_text)
        
        # Filter to only include valid chunk_ids from context
        valid_chunk_ids = {block['chunk_id'] for block in context_blocks}
        valid_citations = [cite for cite in found_citations if cite in valid_chunk_ids]
        
        # Remove duplicates while preserving order
        unique_citations = []
        for cite in valid_citations:
            if cite not in unique_citations:
                unique_citations.append(cite)
        
        return unique_citations


# Global RAG service instance
rag_service = RAGService()
