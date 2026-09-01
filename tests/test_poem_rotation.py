"""The wall picks poems at random, but never the same one twice running.

A plain random draw would show one poem three times in a row and leave
another waiting all afternoon. The rotation is dealt from a shuffled deck
instead: everything switched on comes up once before anything comes round
again. These tests pin down that promise and the awkward cases around it --
poems switched off or deleted mid-deck, a rotation of one, a rotation of
none.
"""

import unittest

from poem_rotation import PoemDeck


def poems(*ids):
    """The shape retrieve_active_poem_entries returns, trimmed to what matters."""
    return [{"id": poem_id, "raw_text": f"poem {poem_id}"} for poem_id in ids]


def deal_many(deck, active, count, previous_id=None):
    """Deal count poems in a row, feeding each one back as the previous."""
    dealt = []
    for _ in range(count):
        poem = deck.deal(active, previous_id=previous_id)
        if poem is None:
            dealt.append(None)
            continue
        dealt.append(poem["id"])
        previous_id = poem["id"]
    return dealt


class EveryPoemBeforeAnyRepeat(unittest.TestCase):
    """The deck's whole reason for existing."""

    def test_a_full_pass_shows_each_poem_exactly_once(self):
        active = poems(1, 2, 3, 4, 5)
        dealt = deal_many(PoemDeck(), active, 5)
        self.assertEqual(sorted(dealt), [1, 2, 3, 4, 5])

    def test_each_pass_is_a_permutation_over_many_cycles(self):
        active = poems(1, 2, 3, 4)
        dealt = deal_many(PoemDeck(), active, 40)
        for start in range(0, 40, 4):
            self.assertEqual(
                sorted(dealt[start:start + 4]),
                [1, 2, 3, 4],
                f"the pass starting at {start} was not a full sweep: {dealt}"
            )

    def test_the_order_is_not_the_library_order(self):
        # Not a guarantee on any single deal, so this asks whether the deck
        # ever departs from the fixed order the old rotation walked.
        active = poems(*range(1, 9))
        in_order = list(range(1, 9))
        self.assertTrue(
            any(deal_many(PoemDeck(), active, 8) != in_order for _ in range(40)),
            "40 passes all came out in library order, so nothing is shuffling"
        )


class NoRepeatAcrossTheSeam(unittest.TestCase):
    """The poem that was just up must not open the next deck."""

    def test_no_poem_follows_itself_over_many_deals(self):
        active = poems(1, 2, 3)
        dealt = deal_many(PoemDeck(), active, 300)
        doubles = [
            (first, second)
            for first, second in zip(dealt, dealt[1:])
            if first == second
        ]
        self.assertEqual(doubles, [], f"a poem followed itself: {dealt}")

    def test_an_adversarial_shuffle_still_cannot_repeat(self):
        # A shuffle that always deals the poem just shown first is the worst
        # case the seam has to survive.
        active = poems(1, 2, 3)

        def always_put_two_first(cards):
            cards.sort(key=lambda poem_id: poem_id != 2)

        deck = PoemDeck(shuffle=always_put_two_first)
        dealt = deal_many(deck, active, 9)

        self.assertNotIn((2, 2), list(zip(dealt, dealt[1:])))
        for start in range(0, 9, 3):
            self.assertEqual(sorted(dealt[start:start + 3]), [1, 2, 3])

    def test_a_hand_picked_poem_does_not_come_round_again_next(self):
        # Showing a poem by hand spends its turn, so the deck must step over
        # its card instead of dealing the same poem twice running.
        active = poems(1, 2, 3)
        for hand_picked in (1, 2, 3):
            deck = PoemDeck()
            deck.deal(active)
            self.assertNotEqual(
                deck.deal(active, previous_id=hand_picked)["id"],
                hand_picked,
                f"poem {hand_picked} repeated after being shown by hand"
            )

    def test_the_last_card_is_not_dealt_twice_after_a_hand_pick(self):
        # The deck is down to one card and that card is the poem already up.
        active = poems(1, 2)
        deck = PoemDeck()
        first = deck.deal(active)["id"]
        remaining = deck.remaining[0]
        self.assertNotEqual(
            deck.deal(active, previous_id=remaining)["id"],
            remaining,
            "the one card left repeated the poem that was already up"
        )
        self.assertNotEqual(first, remaining)


class TheRotationChangesUnderneath(unittest.TestCase):
    """Poems get switched off, deleted and added while the deck is live."""

    def test_a_poem_switched_off_mid_deck_is_never_dealt(self):
        deck = PoemDeck()
        deck.deal(poems(1, 2, 3, 4))

        still_on = poems(1, 2, 3)
        dealt = deal_many(deck, still_on, 12)

        self.assertNotIn(4, dealt, f"a poem out of the rotation was dealt: {dealt}")
        self.assertEqual(set(dealt), {1, 2, 3})

    def test_a_deleted_poem_is_stepped_over_rather_than_crashing(self):
        deck = PoemDeck()
        deck.deal(poems(1, 2, 3))
        # Everything but 1 is gone from the library entirely.
        self.assertEqual(deal_many(deck, poems(1), 3), [1, 1, 1])

    def test_a_deck_of_nothing_but_departed_poems_is_cut_again(self):
        deck = PoemDeck()
        deck.deal(poems(1, 2, 3))
        # Not one of the cards left in the deck still exists.
        dealt = deck.deal(poems(7, 8))
        self.assertIn(dealt["id"], (7, 8))

    def test_a_poem_added_mid_deck_joins_at_the_next_cut(self):
        active = poems(1, 2)
        deck = PoemDeck()
        deal_many(deck, active, 2)

        widened = poems(1, 2, 3)
        dealt = deal_many(deck, widened, 3)
        self.assertEqual(sorted(dealt), [1, 2, 3])


class RotationsTooSmallToShuffle(unittest.TestCase):
    """One poem, and none at all."""

    def test_a_single_poem_simply_comes_up_again(self):
        # Unavoidable, and the right behaviour: there is nothing to alternate
        # with, and the wall should not go blank.
        self.assertEqual(deal_many(PoemDeck(), poems(9), 4), [9, 9, 9, 9])

    def test_a_single_poem_repeats_even_when_named_as_previous(self):
        self.assertEqual(PoemDeck().deal(poems(9), previous_id=9)["id"], 9)

    def test_an_empty_rotation_deals_nothing_instead_of_raising(self):
        deck = PoemDeck()
        self.assertIsNone(deck.deal([]))
        self.assertIsNone(deck.deal([], previous_id=3))

    def test_an_emptied_rotation_recovers_when_a_poem_comes_back(self):
        deck = PoemDeck()
        deck.deal(poems(1, 2))
        self.assertIsNone(deck.deal([], previous_id=1))
        self.assertEqual(deck.deal(poems(5), previous_id=1)["id"], 5)


if __name__ == "__main__":
    unittest.main()
