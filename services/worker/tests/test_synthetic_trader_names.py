from __future__ import annotations

import re
import unittest
from random import Random

from app.synthetic_traders.names import FIRST_NAMES, LAST_NAMES, generate_persona_name


class SyntheticTraderNameTests(unittest.TestCase):
    def test_seeded_generation_is_reproducible_and_unique(self) -> None:
        first_used: set[str] = set()
        second_used: set[str] = set()
        first_random = Random(712)
        second_random = Random(712)
        first = [generate_persona_name(first_random, first_used) for _ in range(250)]
        second = [generate_persona_name(second_random, second_used) for _ in range(250)]

        self.assertEqual(first, second)
        self.assertEqual(len(first_used), 250)

    def test_handles_have_realistic_weighted_variation(self) -> None:
        random_source = Random(20260915)
        used: set[str] = set()
        names = [generate_persona_name(random_source, used) for _ in range(1000)]
        handles = [name.handle for name in names]

        self.assertTrue(all(re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", handle) for handle in handles))
        self.assertTrue(any("." in handle for handle in handles))
        self.assertTrue(any("_" in handle for handle in handles))
        self.assertTrue(any("-" in handle for handle in handles))
        self.assertTrue(any(any(character.isdigit() for character in handle) for handle in handles))
        self.assertTrue(any(not any(character.isdigit() for character in handle) for handle in handles))

    def test_name_corpus_is_substantially_broader_than_original(self) -> None:
        self.assertGreaterEqual(len(set(FIRST_NAMES)), 150)
        self.assertGreaterEqual(len(set(LAST_NAMES)), 140)

if __name__ == "__main__":
    unittest.main()
