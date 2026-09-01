"""The poem as a list of translation units.

A unit is one piece of the poem that carries its own reading: the source
text it covers and the text currently on the page for it. A unit may hold
more words than its source ("Dime," -> "Tell me,") or fewer, which is the
thing a one-word-per-slot grid could never represent.

Units keep the index space the client already renders: units[i] is one
word span on screen, and the separator after it carries the line break.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import re

WHITESPACE_RUN = re.compile(r'(\s+)')


def split_words_and_separators(text: str) -> Tuple[List[str], List[str]]:
    """Split text into tokens plus the whitespace run that follows each one."""
    parts = WHITESPACE_RUN.split((text or '').strip())
    return parts[0::2], parts[1::2]


def normalize_reading(text: str) -> str:
    """Collapse whitespace and case so two renderings can be compared."""
    return ' '.join((text or '').split()).casefold()


def word_sequence(text: str) -> List[str]:
    """Comparable word list: no punctuation, no case.

    This answers "is the same thing still being said", so a comma is noise.
    """
    words = []
    for piece in (text or '').split():
        key = re.sub(r'[^\w]+', '', piece, flags=re.UNICODE).casefold()
        if key:
            words.append(key)
    return words


def surface_sequence(text: str) -> List[str]:
    """Comparable word list keeping punctuation, ignoring case.

    This answers "has the line arrived", and a poem has not arrived at
    "or only that dress?" while it still reads "or only that dress".
    """
    return [piece.casefold() for piece in (text or '').split()]


def reading_distance(current: str, target: str) -> int:
    """Word-level edit distance between two readings.

    Stage 3 uses this as its rule of progress: a revision is only placed
    when it leaves the line strictly closer to the chosen rendering, which
    is what makes the walk terminate instead of circling.
    """
    left = surface_sequence(current)
    right = surface_sequence(target)
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, left_word in enumerate(left, start=1):
        row = [i]
        for j, right_word in enumerate(right, start=1):
            row.append(min(
                previous[j] + 1,
                row[j - 1] + 1,
                previous[j - 1] + (left_word != right_word),
            ))
        previous = row
    return previous[-1]


# Words that may come and go as a scrap is rearranged. Anything not on this
# list is something the poem names, and a rewrite may not simply delete it.
FUNCTION_WORDS = {
    'the', 'a', 'an', 'of', 'to', 'in', 'on', 'at', 'for', 'from', 'by',
    'with', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'it', 'its', 'or', 'and', 'but', 'not', 'do', 'does', 'did', 'has',
    'so', 'if', 'than', 'that', 'this', 'these', 'those', 'only', 'just',
    'i', 'me', 'my', 'you', 'your', 'he', 'him', 'she', 'her', 'we', 'they',
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del', 'al',
    'y', 'o', 'es', 'son', 'está', 'están', 'se', 'su', 'sus', 'en', 'a',
    'lo', 'le', 'que', 'ese', 'esa', 'este', 'esta', 'sólo', 'solo', 'tiene',
}


def drops_content_words(before: str, after: str) -> bool:
    """True when a rewrite deletes something the poem names.

    Rearranging a scrap is the whole point of the phrase stage, so word
    order and function words are free to change. Losing a noun is not a
    rearrangement, it is the scrap quietly getting smaller.
    """
    kept = set(word_sequence(after))
    for word in word_sequence(before):
        if word not in FUNCTION_WORDS and word not in kept:
            return True
    return False


def distribute_words(words: List[str], count: int) -> List[str]:
    """Spread words evenly across a number of spans, keeping their order.

    Only the page's rhythm depends on this. A reading that came back as one
    piece still has to sit in the spans already on screen, or a revision
    would read as the line being replaced rather than changed.
    """
    if count <= 0:
        return []
    groups: List[List[str]] = [[] for _ in range(count)]
    if words:
        for position, word in enumerate(words):
            groups[min(position * count // len(words), count - 1)].append(word)
    return [' '.join(group) for group in groups]


def render_units(texts: List[str], trailings: List[str]) -> str:
    """Join unit texts, skipping empties but keeping their line breaks."""
    pieces = []
    pending = ''
    for index, text in enumerate(texts):
        trailing = trailings[index] if index < len(trailings) else ' '
        if (text or '').strip():
            if pieces:
                pieces.append('\n' * pending.count('\n') if '\n' in pending else ' ')
            pieces.append(text.strip())
            pending = trailing
        elif '\n' in trailing or not pending:
            pending = trailing
    return capitalize_first_letter(''.join(pieces))


@dataclass
class Unit:
    """One piece of the poem and its current reading."""

    source: str
    text: str
    trailing: str = ' '
    visited: bool = False
    settled: bool = False
    state: Optional[dict] = field(default=None, repr=False)

    def is_visible(self) -> bool:
        return bool((self.text or '').strip())


class UnitPoem:
    """The whole poem as units, plus the rendering the page reads from."""

    def __init__(self, units: List[Unit]):
        self.units = units

    # ---------------------------------------------------------------- build

    @classmethod
    def from_text(cls, text: str) -> 'UnitPoem':
        """One unit per source word. Later stages may merge them."""
        words, separators = split_words_and_separators(text)
        units = []
        for index, word in enumerate(words):
            trailing = separators[index] if index < len(separators) else ''
            units.append(Unit(source=word, text=word, trailing=trailing))
        return cls(units)

    # --------------------------------------------------------------- render

    def render(self) -> str:
        """The poem as text, skipping emptied units but keeping line breaks."""
        return render_units(self.texts(), self.separators())

    def texts(self) -> List[str]:
        """Per-unit text, the array the client indexes into."""
        return [unit.text for unit in self.units]

    def separators(self) -> List[str]:
        """Separator after each unit, so the client can group lines."""
        return [unit.trailing for unit in self.units]

    def sources(self) -> List[str]:
        return [unit.source for unit in self.units]

    # ---------------------------------------------------------------- lines

    def line_spans(self) -> List[Tuple[int, int]]:
        """[start, end) unit ranges, one per line of the poem."""
        spans = []
        start = 0
        for index, unit in enumerate(self.units):
            if '\n' in unit.trailing or index == len(self.units) - 1:
                spans.append((start, index + 1))
                start = index + 1
        return [span for span in spans if span[1] > span[0]]

    def line_span_containing(self, unit_index: int) -> Tuple[int, int]:
        for start, end in self.line_spans():
            if start <= unit_index < end:
                return start, end
        return unit_index, unit_index + 1

    def line_index_for(self, unit_index: int) -> int:
        for line_index, (start, end) in enumerate(self.line_spans()):
            if start <= unit_index < end:
                return line_index
        return 0

    # ----------------------------------------------------------------- text

    def source_for_span(self, start: int, end: int) -> str:
        return ' '.join(
            unit.source for unit in self.units[start:end] if unit.source.strip()
        )

    def text_for_span(self, start: int, end: int) -> str:
        return ' '.join(
            unit.text.strip() for unit in self.units[start:end] if unit.is_visible()
        )

    def source_line(self, line_index: int) -> str:
        spans = self.line_spans()
        if line_index >= len(spans):
            return ''
        start, end = spans[line_index]
        return self.source_for_span(start, end)

    def text_line(self, line_index: int) -> str:
        spans = self.line_spans()
        if line_index >= len(spans):
            return ''
        start, end = spans[line_index]
        return self.text_for_span(start, end)

    # ---------------------------------------------------------------- place

    def place_span(self, start: int, end: int, segments: List[str]) -> None:
        """Write a rewrite across a span, using the model's own segmentation.

        One segment per unit keeps the units the page is already showing.
        Fewer segments than units means the model joined them, so the extra
        units are emptied rather than left holding a stale duplicate.
        """
        span_units = self.units[start:end]
        if not span_units:
            return

        segments = [segment.strip() for segment in segments if segment is not None]
        segments = [segment for segment in segments if segment]
        if not segments:
            return

        if len(segments) == 1 and len(span_units) > 1:
            segments = distribute_words(segments[0].split(), len(span_units))
        elif len(segments) > len(span_units):
            head = segments[:len(span_units) - 1]
            tail = ' '.join(segments[len(span_units) - 1:])
            segments = head + [tail]

        for offset, unit in enumerate(span_units):
            unit.text = segments[offset] if offset < len(segments) else ''

    def place_line(self, line_index: int, segments: List[str]) -> None:
        spans = self.line_spans()
        if line_index >= len(spans):
            return
        start, end = spans[line_index]
        self.place_span(start, end, segments)


def capitalize_first_letter(text: str) -> str:
    """Capitalize the first letter of the poem."""
    for index, character in enumerate(text or ''):
        if character.isalpha():
            return text[:index] + character.upper() + text[index + 1:]
    return text or ''
