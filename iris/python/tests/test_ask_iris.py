"""Unit tests for ask_iris.chunk_markdown() — the pure chunking logic.

Runs with a plain stdlib interpreter, no IRIS, OpenAI, or LangChain required:

    python -m unittest discover -s iris/python/tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ask_iris import MAX_CHUNK_CHARS, chunk_markdown  # noqa: E402


class ChunkByHeadingTests(unittest.TestCase):
    def test_splits_into_one_chunk_per_heading_section(self):
        text = "## First\nbody one\n\n## Second\nbody two\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertEqual([c["heading"] for c in chunks], ["First", "Second"])
        self.assertEqual(chunks[0]["text"], "body one")
        self.assertEqual(chunks[1]["text"], "body two")

    def test_every_chunk_carries_the_source_label(self):
        text = "## A\nsomething\n"
        chunks = chunk_markdown(text, "readme.md")
        self.assertTrue(all(c["source"] == "readme.md" for c in chunks))

    def test_text_before_the_first_heading_gets_a_placeholder_heading(self):
        text = "intro paragraph\n\n## Later\nbody\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertEqual(chunks[0]["heading"], "(document start)")
        self.assertEqual(chunks[0]["text"], "intro paragraph")

    def test_headings_up_to_level_four_are_recognized(self):
        text = "#### Deep heading\nbody\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertEqual(chunks[0]["heading"], "Deep heading")

    def test_a_hash_inside_a_code_fence_style_line_without_space_is_not_a_heading(self):
        # A line starting with '#' but no following space/text isn't ATX heading syntax.
        text = "## Real heading\nline one\n#no-space-here\nline two\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertEqual(len(chunks), 1)
        self.assertIn("#no-space-here", chunks[0]["text"])

    def test_empty_sections_produce_no_chunk(self):
        text = "## Empty\n\n## HasBody\nreal content\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["heading"], "HasBody")

    def test_empty_document_produces_no_chunks(self):
        self.assertEqual(chunk_markdown("", "doc.md"), [])


class ChunkLongSectionTests(unittest.TestCase):
    def test_a_section_longer_than_the_max_is_split_into_multiple_chunks(self):
        long_body = "x" * (MAX_CHUNK_CHARS * 2 + 500)
        text = f"## Long\n{long_body}\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["heading"] == "Long" for c in chunks))
        self.assertTrue(all(len(c["text"]) <= MAX_CHUNK_CHARS for c in chunks))

    def test_split_pieces_overlap_so_no_content_is_silently_dropped(self):
        long_body = "".join(f"word{i} " for i in range(2000))
        text = f"## Long\n{long_body}\n"
        chunks = chunk_markdown(text, "doc.md")
        reconstructed = "".join(c["text"] for c in chunks)
        # Every distinct word from the source appears somewhere in the chunked output.
        for word in ["word0", "word999", "word1999"]:
            self.assertTrue(any(word in c["text"] for c in chunks), f"{word} missing from chunks")

    def test_a_short_section_is_not_split(self):
        text = "## Short\njust one short paragraph\n"
        chunks = chunk_markdown(text, "doc.md")
        self.assertEqual(len(chunks), 1)


if __name__ == "__main__":
    unittest.main()
