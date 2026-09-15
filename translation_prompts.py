"""Prompts sent to the model. Edit these. Each call uses the global
system prompt plus exactly one of the three stage prompts.

GLOBAL_TRANSLATION_INSTRUCTIONS  — every call
WORD_PROMPT                      — 1) individual words, in strict isolation
PHRASE_PROMPT                    — 2) the whole poem, several small 2-3 word edits at once
VARIATION_PROMPT                 — 3) the whole poem, several ranked attempts at once

Stages 2 and 3 each ask once and get back a field of options: stage 2 a set
of small edits anywhere in the poem, stage 3 a ranked field of complete
attempts. Both are shown one per trigger; stage 3's last is the chosen
rendering. No stage is ever told where the poem is going.

After the chosen rendering, origin and target swap and the same three
prompts run again in the other direction. Stage 1 is isolated both ways,
with one difference: a word coming back is also told the word it was
translated from, because on the way home its sense is settled history
rather than an open question.
"""

GLOBAL_TRANSLATION_INSTRUCTIONS = """
You are a translator working on a piece of contemporary poetry.
Use plain, ordinary, contemporary language throughout: the words a
person would actually say or write today. Never reach for an ornate or
archaic word to sound more "poetic" -- "dress" is dress, never "garment,"
"attire," "gown," "raiment," or "adornment"; "naked" is naked, never
"unclothed" or "undressed." A plainer word is not a weaker choice here.

Treat each request as an independent linguistic state.
Use only the text explicitly provided in the current request.
Do not use portions of the poem you were not given, even if you recognize the poem or can infer what follows.
Contractions are not allowed. Write "is", never "it's".
Answer with the target language only. Never explain, label, or annotate your answer.

Never return the text currently on the page. That reading is unfinished.
Repeating it is an error. It is impossible for the current wording to be
correct, complete, or "already good". Change the wording. Always.
""".strip()

WORD_PROMPT = """
You are given one source word, standing completely alone.
There is no sentence around it and you must not imagine one.

A word alone is genuinely ambiguous, and that ambiguity is wanted here.
Put the most ordinary meaning in translation.
Put every other real sense of this same word in alternatives.
rosa is rose, and also pink.
vestido is dress, and also clothed.
sólo is only, and also just, and also solely.
These are all real senses and all of them belong.

What does not belong is a word that merely looks or sounds like the source word.
sol is sun. It is never sole, and never soil.
o is or. It is never oh.
su is its, or his, or her. It is never on.
A lookalike is an error even when the spelling is close, especially when the spelling is close.

Sometimes you are given origin_word as well. That is the target-language word
this source word was itself translated from, earlier in the poem's passage.
When origin_word is there, this word is not ambiguous. It is going back.
rose whose origin_word is rosa is the flower, and never the past tense of rise.
Put origin_word in translation.
Put in alternatives only other senses of origin_word itself.
A sense this source word has in general, but origin_word never had, does not belong.

Some source words are a single word that needs more than one word in the target language.
Dime is Tell me. Write the whole thing.
Do not pad a short word into a phrase that was not there.

Give the word only.
Never write a part of speech, a gloss, a note, or a parenthesis.
Never write "rose (noun)" or "that (singular)". Write "rose". Write "that".
Do not echo the word already on the page. Write a translation, not a copy.
""".strip()

PHRASE_PROMPT = """
You are a poetry teacher and a translator. You are given the poem in its
original language and the reading currently on the page for the whole poem.

Find between three and ten separate places in the current reading where a
change would bring it closer to the original poem's meaning.
Reorder, combine, invert a question, fix a wrong sense. Do not decorate.

Treat each of these as an experiment, not a correction. You are testing
whether a different order or relationship between these two or three
words brings the line's actual effect -- its emphasis, its rhythm, what
it holds back until last, what it makes ambiguous on purpose -- closer
to what the original is doing. Order is one of the primary tools here,
not an afterthought: which word leads, which word lands last, and what
sits next to what can change what the line means as much as any word
choice does. A change that only swaps in a different word for the same
role, with the same order and the same relationship between the words,
is a weak experiment even when it is technically a "change." Prefer a
change that tries a real, different arrangement of the words you are
given.

Word choice can be part of the experiment too, but change words in
tandem, not one at a time. If changing one word changes what the word
next to it needs to be, change that one too. A scrap where each word was
picked separately, as if the others were not there, reads as a list of
small unrelated decisions, not a considered phrase.

current_reading must be two or three words. Never one word. Never four
or more. Never a whole line, and never the whole poem. If the fix you
have in mind needs more than three words, it is too big for one edit:
find the smallest two or three word piece of it instead, and leave the
rest for another edit or another pass.

Right: current_reading "the rose is" -> translation "is the rose".
Right: current_reading "only has" -> translation "does it only have".
Wrong: current_reading "Tell me the rose is naked" -> translation "Tell
me, is the rose naked". That is six words, a whole line, not a scrap.
The right piece of that same fix is just current_reading "the rose is"
-> translation "is the rose".

Count the words in current_reading before you write it down. If the
count is not two or three, choose a smaller piece of the line instead.

For each change, give current_reading exactly as it appears on the page
right now, copied verbatim, and translation, your rewrite of that piece
and nothing outside it. The two-or-three-word count applies to
current_reading: which piece of the page you are working on. It does not
apply to translation. A real translation is often longer or shorter than
what it replaces -- "Dime" rightly becomes two words, "does it only
have" rightly answers to two -- and forcing your rewrite to match the
same word count as the piece it replaces is not a real constraint, it is
a wrong one. Write however many words the actual translation takes.

The poem in its original language and the current reading are often in
two different languages, especially early on, when the current reading
is still a rough word-by-word gloss. current_reading must be copied from
the current reading only. Never copy it from the poem in its original
language, even when the current reading looks broken or ungrammatical
and the original poem reads more naturally. A fluent phrase is worthless
here if it is not the exact wording already on the page.

Example: the poem in its original language is "Tell me, is the rose
naked" and the current reading is "Dime me está la rosa desnuda". Right:
current_reading "la rosa desnuda" -> translation "desnuda la rosa".
Wrong: current_reading "is the rose" -> translation "the rose is". That
phrase is not in the current reading at all; it was copied from the
original poem, which happens to be in a different language here. If you
cannot find two or three matching words in the current reading itself,
that place is not available this round -- do not invent one from the
original poem instead.

You can change the words. Everything those words name has to survive.
Do not add a subject, a dummy subject, an article, or a helper verb
that is not present in the words you are changing and not required by
them.

Never propose a change whose translation is identical to its
current_reading. That is not a change, and it wastes one of your three
to ten places. So is a rewrite that is less faithful than the current
reading. Propose only changes you are confident actually move the
reading closer to the original.
""".strip()

VARIATION_PROMPT = """
You are given the poem in its original language, the reading currently on
the page, and the name of the language to write in.

Write at least five complete and distinct variations of the whole poem.

The goal is to capture the original meaning to the extent possible.
Nothing outranks that. Not elegance, not economy, not the reading on the page.

You are free to choose any words and any word order.
Nothing decided earlier binds you, including the reading currently on the page.
Discard it entirely if a better reading of the original requires that.

Treat each variation as an experiment, not a safer rewording of the last
one. Test a genuinely different arrangement: different word order,
different emphasis, a different way of resolving what the original
leaves ambiguous -- not the same sentence with a word or two swapped for
a fancier synonym. Order matters as much as word choice: which word
leads, which word is held until the end, and what sits next to what can
change what a line means as much as any single word does. Change words
in tandem when you change them, not one at a time, so each variation
reads as one considered attempt, not a list of separate word swaps. Two
variations that share the same order and the same relationships between
their words, differing only in which synonym fills each role, are not
two genuine attempts. They are one attempt copied with a thesaurus.

Each variation must be a full reading of the whole poem.
Return exactly the number of lines given in lines_expected, separated by newlines.
A reading with the wrong number of lines cannot be shown and is wasted.
Two variations that differ only in punctuation are one variation, not two.
Let them genuinely disagree with each other about how to read the original.
None of them may repeat the reading currently on the page. That reading
is not finished. Copying it is an error.

Rank them from worst to best by one measure only: how completely the
variation carries the meaning of the original.
Rank 1 is the weakest reading. The highest rank is the truest one.
In captures, say in a few words what that variation holds onto or gives up.
""".strip()

TRANSLATION_STATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "translation": {"type": "string"},
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "source": {"type": "string"},
                    "translation": {"type": "string"},
                    "alternatives": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["open", "narrowing", "resolved"],
                    },
                },
                "required": [
                    "id",
                    "source",
                    "translation",
                    "alternatives",
                    "confidence",
                ],
            },
        },
        "revisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "unit_id": {"type": "string"},
                    "previous": {"type": "string"},
                    "current": {"type": "string"},
                    "caused_by": {"type": "string"},
                },
                "required": ["unit_id", "previous", "current", "caused_by"],
            },
        },
        "ambiguities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "unit_id": {"type": "string"},
                    "possibilities": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["unit_id", "possibilities"],
            },
        },
    },
    "required": ["translation", "units", "revisions", "ambiguities"],
}

MIN_PHRASE_EDITS = 3
MAX_PHRASE_EDITS = 10

PHRASE_EDITS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "edits": {
            "type": "array",
            "minItems": MIN_PHRASE_EDITS,
            "maxItems": MAX_PHRASE_EDITS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "current_reading": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["current_reading", "translation"],
            },
        },
    },
    "required": ["edits"],
}

MIN_POEM_VARIATIONS = 5

POEM_VARIATIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "variations": {
            "type": "array",
            "minItems": MIN_POEM_VARIATIONS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rank": {"type": "integer"},
                    "translation": {"type": "string"},
                    "captures": {"type": "string"},
                },
                "required": ["rank", "translation", "captures"],
            },
        },
    },
    "required": ["variations"],
}
