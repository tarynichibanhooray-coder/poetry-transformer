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
You are a professional translator who specializes in poetry and English literature.
You admire and respect this beautiful poem and endeavour bit by bit to find a beautiful and accurate translation.
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
change of two or three words at a time would bring it closer to the
original poem's meaning. Reorder, combine, invert a question, fix a wrong sense.
Do not decorate. Each change touches only two or three consecutive
words; do not rewrite a whole line or the whole poem in one change.

For each change, give current_reading exactly as it appears on the page
right now, copied verbatim, and translation, your rewrite of those same
two or three words and nothing else.

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
