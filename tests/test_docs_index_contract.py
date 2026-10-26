"""Issue #290: the docs index must reference every page in docs/.

A shipped feature whose guide is never linked from docs/README.md is
undiscoverable, and internal records left unlabelled read as instructions.
This offline contract fails when a docs page is added (or renamed) without
an index entry, so index drift fails CI instead of reaching readers.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class DocsIndexContract(unittest.TestCase):
    def test_every_docs_page_is_referenced_in_the_index(self):
        index = (DOCS / "README.md").read_text()
        pages = sorted(p.name for p in DOCS.glob("*.md") if p.name != "README.md")
        self.assertTrue(pages)
        for page in pages:
            with self.subTest(page=page):
                self.assertIn(
                    page, index,
                    f"docs/{page} is not referenced in docs/README.md; "
                    "link it under the right section, or under "
                    "'Internal and historical records' if it is a record, "
                    "not a guide.")


if __name__ == "__main__":
    unittest.main()
