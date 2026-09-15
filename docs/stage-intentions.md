# Stage intentions

This is the product. Prompts, engine comments, and tests must follow it.
They do not replace it.

The wall is HTTP only. One live poem. Space, a tap, or `POST /trigger` is
one trigger. One trigger is one user-visible action on the wall.

Three stages outward. Then the languages swap and the same three stages
run home. Each word remembers what it was translated from on the way out.

No stage is told the stored destination except as already written below.
Never return the text currently on the page. That reading is unfinished.
Repeating it is an error. Change the wording. Always.

The one resting exceptions: the exact stored target on the way out, and
the exact original on the way home.

After a full outward-and-return journey, the next trigger deals another
active poem. Rotation is the shuffled active deck, with no immediate
repeat. `/poems/{id}` is the edit page, not the wall.

---

## Stage 1 — words

One isolated source word. No sentence around it. Do not invent one.

The model returns the ordinary primary sense and every other real sense
of that same word. Lookalikes are not senses. On the way home the word
is not ambiguous: `origin_word` is settled history, and that is the
primary.

One trigger takes one word. The wall plays the other senses through that
slot, then settles on the primary. The primary is only the last reading.
That cycle is Stage 1. Flattening it into a single swap is not Stage 1.

The papers stay torn. Stage 1 is the only stage that stays unhealed.

Give the word only. No part of speech, gloss, note, or parenthesis.

---

## Stage 2 — scraps

One model call. Between three and ten distinct edits across the whole
poem. Each edit is a change of two or three words: reorder, combine,
invert a question, fix a wrong sense. Do not decorate, and do not rewrite
a whole line or the whole poem in one edit.

The model picks where to make each edit. It is not told which words to
change; it is given the poem and the current page and finds its own three
to ten places. Each edit names the exact wording it replaces, copied
verbatim off the current page, and its rewrite of those same words.

They are applied one edit per trigger, in the order offered. Everything a
scrap names has to survive: an edit may not drop a noun, a verb, or an
image, and may not add a subject, dummy subject, article, or helper that
is not in the words it is changing and not required by them.

An edit whose rewrite is identical to the wording it replaces is not a
change and is skipped in favor of the next one. So is an edit whose named
wording can no longer be found on the page, because an earlier edit in
the same batch already touched those words. Fewer than three edits is a
failed call.

When Stage 2 changes scraps, those scraps combine and the papers heal.

---

## Stage 3 — the whole poem

One model call. At least five distinct full attempts at the whole poem.
Fidelity to the original outranks elegance, economy, and the reading on
the page. Nothing decided earlier binds this stage.

They are shown one attempt per trigger, worst first. The last one shown
is the stored final for that direction. The papers heal. This is a whole
reading, not torn scraps.

Fewer than five, or two that differ only in punctuation, is a failed
call. None may repeat the current page.

---

## Return

Origin and target swap. Stages 1, 2, and 3 run again toward the original
language. Stage 1 stays isolated both ways. The difference is
`origin_word` on the way home.
