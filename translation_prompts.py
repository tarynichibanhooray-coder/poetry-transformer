"""Prompts sent to the model. Edit these. Each call uses the global
system prompt plus exactly one of the three stage prompts.

GLOBAL_TRANSLATION_INSTRUCTIONS  — every call
WORD_PROMPT                      — 1) individual words, in strict isolation
PHRASE_PROMPT                    — 2) a 2–3 word scrap, with its line as context
VARIATION_PROMPT                 — 3) the whole poem, several ranked attempts at once

Stage 3 asks once and gets back a ranked field of complete attempts. They
are shown one per trigger, worst first, and the chosen rendering is shown
last. No stage is ever told where the poem is going.

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
""".strip()

PHRASE_PROMPT = """
You are given a short scrap of the poem, two or three words long:
the source words, the reading currently on the page for them,
and the full source line the scrap was taken from.

The reading on the page was built one word at a time, so it is a gloss
sitting in source order. Your work is to make that scrap read as the
target language. You are revising a reading, not starting a new one.

Move the words into the order the target language actually wants.
Invert a question. Unstack a gloss that is still in source order:
"the rose is" should become "is the rose".
Combine two words into one, or open one into two, where that is honest.
Correct a word whose sense is wrong now that you can see the line.

Everything the scrap names has to survive.
If the scrap contains rosa, your answer contains rose.
Never drop a noun, a verb, or an image because it appears elsewhere in the line.
The line is shown to you for grammar and sense only.

Do not add a subject, a dummy subject, an article, or a helper verb
that is not present in this scrap and not required by the words in it.
Do not translate the rest of the line. Return this scrap alone.
If the scrap is still genuinely ambiguous by itself, leave it ambiguous.
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

POEM_VARIATIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "variations": {
            "type": "array",
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
