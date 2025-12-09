"""
Block splitting logic for HTML documents using breadcrumb-based approach.

This module traverses the DOM tree while maintaining a stack of ancestor headings
(breadcrumbs), and groups all content elements with identical breadcrumbs into blocks.
"""

from bs4 import BeautifulSoup, Tag, NavigableString
from typing import List, Dict, Any
import re
from knowledge.pipeline.data_models import Block
from knowledge.pipeline.html_utils import decode_html_entities


class HeadingStack:
    """Manages the heading hierarchy stack during DOM traversal."""

    def __init__(self):
        self.stack: List[Dict[str, Any]] = []

    def push(self, level: int, text: str):
        """
        Add a heading to the stack.

        Automatically pops any headings at same or lower level before adding.
        This ensures the stack always represents the current hierarchical path.

        Args:
            level: Heading level (1-6 for h1-h6)
            text: Cleaned heading text
        """
        while self.stack and self.stack[-1]['level'] >= level:
            self.stack.pop()


        self.stack.append({'level': level, 'text': text})

    def get_breadcrumbs(self) -> List[str]:
        """Get the current breadcrumb path as a list of heading texts."""
        return [h['text'] for h in self.stack]

    def get_breadcrumb_key(self) -> str:
        """Get a unique string key for the current breadcrumbs."""
        if not self.stack:
            return "__no_heading__"
        return "::".join(self.get_breadcrumbs())

    def is_empty(self) -> bool:
        """Check if the stack is empty."""
        return len(self.stack) == 0

    def copy(self) -> 'HeadingStack':
        """Create a copy of the current stack."""
        new_stack = HeadingStack()
        new_stack.stack = [h.copy() for h in self.stack]
        return new_stack


def clean_heading_text(heading: Tag) -> str:
    """
    Extract and clean text from a heading tag.

    Args:
        heading: BeautifulSoup Tag object for a heading

    Returns:
        Cleaned heading text
    """
    if not heading:
        return ""

    text = heading.get_text(separator=' ', strip=True)
    text = decode_html_entities(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def clean_text(text: str) -> str:
    """
    Clean text by decoding HTML entities and normalizing whitespace.

    Args:
        text: Raw text possibly containing HTML entities

    Returns:
        Cleaned text with decoded entities
    """
    text = decode_html_entities(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_content_elements(soup: BeautifulSoup, heading_stack: HeadingStack) -> Dict[str, List[Dict[str, Any]]]:
    """
    Traverse the DOM and group content elements by their breadcrumb path.

    This function maintains a heading stack and groups all content elements
    (paragraphs, list items, table cells) that share the same breadcrumbs.

    Args:
        soup: BeautifulSoup object
        heading_stack: HeadingStack to track breadcrumbs

    Returns:
        Dictionary mapping breadcrumb keys to lists of content elements
    """
    grouped_content: Dict[str, List[Dict[str, Any]]] = {}

    def add_content_element(element_type: str, text: str, breadcrumb_key: str, breadcrumbs: List[str]):
        """Helper to add a content element to the grouped_content."""
        if breadcrumb_key not in grouped_content:
            grouped_content[breadcrumb_key] = []

        grouped_content[breadcrumb_key].append({
            'type': element_type,
            'text': text,
            'breadcrumbs': breadcrumbs.copy()
        })

    def has_direct_text_content(element: Tag) -> bool:
        """Check if element has direct text content (not just in children)."""
        if not isinstance(element, Tag):
            return False
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text and not text.startswith('<!--'):
                    return True
        return False

    def process_element(element):
        """Recursively process HTML elements."""
        if isinstance(element, NavigableString):
            return

        if not isinstance(element, Tag):
            return

        if element.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            level = int(element.name[1])
            heading_text = clean_heading_text(element)

            if heading_text:
                heading_stack.push(level, heading_text)
            return


        if element.name in ('ul', 'ol'):
            for li in element.find_all('li', recursive=False):
                text = clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    breadcrumb_key = heading_stack.get_breadcrumb_key()
                    breadcrumbs = heading_stack.get_breadcrumbs()
                    add_content_element('list_item', text, breadcrumb_key, breadcrumbs)
            return


        if element.name == 'table':
            for row in element.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if cells:
                    row_text = ' | '.join(clean_text(cell.get_text(separator=' ', strip=True)) for cell in cells)
                    if row_text:
                        breadcrumb_key = heading_stack.get_breadcrumb_key()
                        breadcrumbs = heading_stack.get_breadcrumbs()
                        add_content_element('table_row', row_text, breadcrumb_key, breadcrumbs)
            return

        if element.name == 'p':
            text = clean_text(element.get_text(separator=' ', strip=True))
            if text:
                breadcrumb_key = heading_stack.get_breadcrumb_key()
                breadcrumbs = heading_stack.get_breadcrumbs()
                add_content_element('paragraph', text, breadcrumb_key, breadcrumbs)
            return

        if element.name in ('div', 'section', 'article', 'main', 'body', 'header', 'footer', 'nav', 'aside'):
            if has_direct_text_content(element) and element.name == 'div':
                text = clean_text(element.get_text(separator=' ', strip=True))
                if text:
                    breadcrumb_key = heading_stack.get_breadcrumb_key()
                    breadcrumbs = heading_stack.get_breadcrumbs()
                    add_content_element('paragraph', text, breadcrumb_key, breadcrumbs)
                return

            for child in element.children:
                process_element(child)
            return

        for child in element.children:
            process_element(child)

    process_element(soup)

    return grouped_content


def create_blocks_from_grouped_content(
    grouped_content: Dict[str, List[Dict[str, Any]]],
    source_url: str
) -> List[Block]:
    """
    Create Block objects from grouped content.

    Args:
        grouped_content: Dictionary mapping breadcrumb keys to content elements
        source_url: Source URL/filename

    Returns:
        List of Block objects
    """
    blocks = []

    for breadcrumb_key, content_elements in grouped_content.items():
        if not content_elements:
            continue

        breadcrumbs = content_elements[0]['breadcrumbs']

        block = Block(
            block_id='',
            breadcrumbs=breadcrumbs,
            content_elements=content_elements,
            source_url=source_url,
            metadata={
                'num_elements': len(content_elements)
            }
        )

        blocks.append(block)

    return blocks


def split_html_into_blocks(html_content: str, source_url: str) -> List[Block]:
    """
    Split HTML document into logical blocks based on breadcrumb grouping.

    This function:
    1. Traverses the DOM tree while maintaining a heading stack
    2. Groups all content elements with identical breadcrumbs into the same block
    3. Returns a list of Block objects

    The breadcrumb hierarchy can be irregular (e.g., h1→h3, h2→h5) - it just
    records whatever ancestor headings exist above each content element.
    """
    soup = BeautifulSoup(html_content, 'lxml')


    heading_stack = HeadingStack()


    for h1 in soup.find_all('h1', limit=5):
        heading_text = clean_heading_text(h1)
        if heading_text:
            heading_stack.push(1, heading_text)
            break


    main_content = soup.find('main') or soup.find('article') or soup.body or soup

    if not main_content:
        return []


    grouped_content = extract_content_elements(main_content, heading_stack)


    blocks = create_blocks_from_grouped_content(grouped_content, source_url)


    if not blocks:
        text = clean_text(main_content.get_text(separator=' ', strip=True))
        if text:
            block = Block(
                block_id='',
                breadcrumbs=['Document Content'],
                content_elements=[{'type': 'text', 'text': text, 'breadcrumbs': ['Document Content']}],
                source_url=source_url,
                metadata={'num_elements': 1}
            )
            blocks.append(block)

    return blocks
