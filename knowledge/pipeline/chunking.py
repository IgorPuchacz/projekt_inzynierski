"""
Chunking module for extracting chunks from blocks.

This module takes Block objects and converts them into Chunk objects
with breadcrumb context for embedding.
"""

from typing import List, Optional
import re
import nltk
from knowledge.pipeline.data_models import Block, Chunk, ChunkingConfig


try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)


class Chunker:
    """Extracts chunks from blocks."""

    def __init__(self, config: Optional[ChunkingConfig] = None):
        self.config = config or ChunkingConfig()
        self.sent_tokenizer = nltk.data.load('tokenizers/punkt/polish.pickle')

    def chunk_block(self, block: Block) -> List[Chunk]:
        """
        Extract chunks from a block with breadcrumb context.
        """
        chunks = []

        for element in block.content_elements:
            element_type = element['type']
            text = element['text']

            if element_type == 'paragraph':
                word_count = len(text.split())
                if word_count <= 20 and block.breadcrumbs:
                    chunk = self._create_chunk(
                        text,
                        'paragraph',
                        block
                    )
                    if chunk:
                        chunks.append(chunk)
                else:
                    sentences = self.sent_tokenizer.tokenize(text)
                    for sentence in sentences:
                        chunk = self._create_chunk(
                            sentence.strip(),
                            'sentence',
                            block
                        )
                        if chunk:
                            chunks.append(chunk)

            elif element_type == 'list_item':
                chunk = self._create_chunk(
                    text,
                    'list_item',
                    block
                )
                if chunk:
                    chunks.append(chunk)

            elif element_type == 'table_row':
                chunk = self._create_chunk(
                    text,
                    'table_row',
                    block
                )
                if chunk:
                    chunks.append(chunk)

            elif element_type == 'text':
                sentences = self.sent_tokenizer.tokenize(text)
                for sentence in sentences:
                    chunk = self._create_chunk(
                        sentence.strip(),
                        'sentence',
                        block
                    )
                    if chunk:
                        chunks.append(chunk)

        return chunks

    def _create_chunk(
        self,
        content: str,
        element_type: str,
        block: Block
    ) -> Optional[Chunk]:
        """
        Create a Chunk object from content.

        Args:
            content: The text content
            element_type: Type of element (sentence, list_item, table_row)
            block: Parent block

        Returns:
            Chunk object or None if filtered out
        """
        content = content.strip()

        if not content:
            return None

        word_count = len(content.split())


        if element_type in ('list_item', 'table_row'):
            min_words = 3
        elif element_type == 'paragraph' and block.breadcrumbs:
            min_words = 3
        elif element_type == 'sentence' and block.breadcrumbs:
            min_words = 5
        else:
            min_words = self.config.min_words_per_chunk

        if word_count < min_words:
            return None

        if self.config.filter_metadata_lines:
            if self._is_metadata_line(content):
                return None


        if self.config.filter_fragments:
            if element_type not in ('list_item', 'table_row', 'paragraph'):
                if self._is_fragment(content):
                    return None


        if content.strip() in self.config.generic_headings:
            return None


        if word_count == 1 and not self._is_meaningful_single_word(content):
            return None


        embedding_text = self._create_embedding_text(block.breadcrumbs, content)


        chunk = Chunk(
            chunk_id='',
            breadcrumbs=block.breadcrumbs.copy(),
            content=content,
            embedding_text=embedding_text,
            parent_block_id=block.block_id,
            metadata={
                'breadcrumbs': block.breadcrumbs.copy(),
                'element_type': element_type,
                'word_count': word_count,
                'source_url': block.source_url,
            }
        )

        return chunk

    def _create_embedding_text(self, breadcrumbs: List[str], content: str) -> str:
        """
        Create embedding text by combining breadcrumbs with content.

        Args:
            breadcrumbs: List of heading texts
            content: The chunk content

        Returns:
            Formatted embedding text
        """
        if not breadcrumbs:
            return content

        breadcrumb_text = " - ".join(breadcrumbs)
        return f"{breadcrumb_text} - {content}"

    def _is_metadata_line(self, text: str) -> bool:
        """Check if text looks like metadata."""
        for pattern in self.config.metadata_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _is_fragment(self, text: str) -> bool:
        """Check if text is a sentence fragment."""
        if text and text[0].islower():
            return True

        if len(text.split()) <= 3 and not text.rstrip().endswith(('.', '!', '?', ':', '...')):
            return True

        return False

    def _is_meaningful_single_word(self, text: str) -> bool:
        """Check if a single word is meaningful enough to keep."""
        if re.match(r'\d+', text):
            return True
        return False


def chunk_blocks(blocks: List[Block], config: Optional[ChunkingConfig] = None) -> List[Chunk]:
    """
    Convenience function to chunk multiple blocks.

    Args:
        blocks: List of Block objects
        config: Optional ChunkingConfig

    Returns:
        List of all Chunk objects from all blocks
    """
    chunker = Chunker(config)
    all_chunks = []

    for block in blocks:
        chunks = chunker.chunk_block(block)
        all_chunks.extend(chunks)

    return all_chunks
