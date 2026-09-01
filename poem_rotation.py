"""The order the wall shows poems in: a shuffled deck, not a fixed loop.

Every poem in the rotation comes up once before any of them comes round
again. A plain random draw could not promise that -- it would happily show
the same poem three times running -- so the order is dealt from a deck
instead. When the deck runs out it is cut again, and the poem that was just
up is never dealt first, so there is no repeat across that seam either.

The rotation changes underneath the deck while the installation is running:
poems are switched on and off, added, and deleted. The deck holds ids only
and checks them against the live rotation as it deals, so a card for a poem
that has since gone simply falls out.
"""

import random
from typing import Callable, Dict, List, Optional, Sequence


class PoemDeck:
    """Deals active poems in a shuffled order, once each before repeating."""

    def __init__(self, shuffle: Callable[[List[int]], None] = random.shuffle):
        # Injected so a test can deal a known order.
        self._shuffle = shuffle
        self._remaining: List[int] = []

    @property
    def remaining(self) -> List[int]:
        """The cards still to be dealt, for tests and the status endpoint."""
        return list(self._remaining)

    def deal(
        self,
        active_poems: Sequence[Dict],
        previous_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """The next poem to show, or None when nothing is in the rotation.

        Passing the poem currently up as previous_id keeps a fresh cut from
        opening on it. With a single poem in the rotation there is nothing to
        alternate with, so it simply comes up again.
        """
        by_id = {poem["id"]: poem for poem in active_poems}
        if not by_id:
            self._remaining = []
            return None

        self._discard_departed(by_id)
        if not self._remaining:
            self._cut(by_id)

        if len(by_id) > 1 and self._remaining[:1] == [previous_id]:
            # The poem already up must not come round again straight away:
            # not across a fresh cut, and not after one was shown by hand
            # out of turn. If its card is all that is left of the deck then
            # its turn is spent, so cut again rather than repeat it.
            if len(self._remaining) == 1:
                self._cut(by_id)
            if self._remaining[0] == previous_id:
                self._remaining.append(self._remaining.pop(0))

        return by_id[self._remaining.pop(0)]

    def _discard_departed(self, by_id: Dict[int, Dict]) -> None:
        """Drop cards for poems that have left the rotation since the cut."""
        self._remaining = [
            poem_id for poem_id in self._remaining if poem_id in by_id
        ]

    def _cut(self, by_id: Dict[int, Dict]) -> None:
        cards = list(by_id)
        self._shuffle(cards)
        self._remaining = cards
