"""
OpenAI Translator for Poetry Transformer
Handles all AI translation requests with structured JSON output
"""

import json
from typing import List, Dict, Optional
from openai import OpenAI, OpenAIError

import config


# Parts of speech that have one ordinary equivalent and no synonyms worth
# offering. An article is "the"; a translation that offers "her" for "la" has
# changed the word's job, and one that offers "a" has changed which article it
# is. Enforced in code because a rule in a prompt is only a request.
FUNCTION_WORD_PARTS_OF_SPEECH = {
    'article',
    'determiner',
    'pronoun',
    'preposition',
    'conjunction',
    'auxiliary',
    'particle',
}


class OpenAITranslator:
    """Manages communication with OpenAI API for translations"""

    def __init__(self, api_key: str = None):
        """
        Initialize OpenAI translator with API key
        
        Args:
            api_key: OpenAI API key (defaults to config)
        """
        self.api_key = api_key or config.OPENAI_API_KEY
        self.client = OpenAI(api_key=self.api_key)
        self.model = config.OPENAI_MODEL
        if config.DEBUG_MODE:
            print(f"✓ OpenAI Translator initialized with model: {self.model}")

    def request_word_translation_with_synonyms(
        self,
        source_word: str,
        source_language: str,
        target_language: str,
        context_line: str = None,
        whole_poem: str = None,
        arriving_at: str = None
    ) -> Dict:
        """
        Request translation of a single word with synonyms from OpenAI
        
        Args:
            source_word: Word to translate
            source_language: Name of source language
            target_language: Name of target language
            context_line: Line of the poem the word appears in, used to pick
                the sense that fits rather than the word's most common sense
            whole_poem: The complete original poem, since the word is being
                chosen for this poem and not for a dictionary
            arriving_at: The finished translation the poem is coming to rest
                on, where the poem was given one
            
        Returns:
            Dictionary with 'part_of_speech', 'primary_translation' and 'synonyms'
        """
        context_block = (
            f'The line it appears in:\n"{context_line}"\n'
            if context_line else
            'No surrounding line is available.\n'
        )

        if whole_poem:
            context_block += f'\n        The whole poem:\n"""\n{whole_poem}\n"""\n'

        if arriving_at:
            context_block += (
                '\n        The finished translation this poem is coming to '
                f'rest on:\n"""\n{arriving_at}\n"""\n'
            )

        prompt = f"""
        A poem is being translated from {source_language} to {target_language}
        one word at a time. Work out how the word "{source_word}" should be
        translated, and what the honest alternatives to that choice are.

        {context_block}
        The alternatives are shown to a reader one after another before the
        word settles on your primary translation, so they are the substance of
        the piece: they should be the renderings a translator would genuinely
        weigh, and the reader should learn something about the word by seeing
        them.

        Return a JSON object with exactly this format:
        {{
            "part_of_speech": "noun | verb | adjective | adverb | article | determiner | pronoun | preposition | conjunction | auxiliary | particle | other",
            "primary_translation": "the rendering the poem should keep",
            "synonyms": ["a real alternative", "another"]
        }}

        Rules:
        - "part_of_speech" is the part of speech of "{source_word}" in that line.
        - "primary_translation" is the one the finished poem should keep. Judge
          it on the sense the line needs first, then on register and sound in
          the poem as a whole. It is a choice, not a default: the word a
          translator would defend.
        - "synonyms" are the other renderings worth weighing, best first. Give
          every one that is true, up to {config.MAX_SYNONYMS_PER_WORD}. A rich
          word deserves several; do not pad a plain one.
        - Every alternative must be the SAME part of speech as the primary and
          must be substitutable for it in that line with the line still meaning
          what it meant. If it fails that test it is not an alternative, it is
          a different word.
        - Do NOT offer another sense of the word. If the word is the flower
          "rose", do not offer colours such as "pink" or "salmon".
        - Function words carry no such choice. If "{source_word}" is an article,
          determiner, pronoun, preposition, conjunction, auxiliary or particle,
          give the single ordinary {target_language} equivalent and an EMPTY
          synonyms list. A definite article is "the" and nothing else: not "a",
          not "her", not "him".
        - Prefer the plain word a poet would use. Do not reach for a formal or
          Latinate word where a common one is what the line says: "tell me",
          not "inform me"; "has", not "possesses".
        {self.describe_word_arrival_rule(arriving_at)}
        - Keep each rendering concise (1-2 words max).

        Return ONLY the JSON object, no additional text.
        """

        response = self.send_message_to_openai_and_parse_json(prompt)
        return self.strip_synonyms_from_function_words(response)

    def describe_word_arrival_rule(self, arriving_at: str = None) -> str:
        """
        Tie a word's chosen rendering to the ending the poem is heading for

        Args:
            arriving_at: The finished translation the poem will come to rest on

        Returns:
            The rule, or an empty string when the poem has no chosen ending
        """
        if not arriving_at:
            return ''

        return (
            "- Where the finished translation above renders this word, and its\n"
            "          rendering is a fair translation of the word, make that your\n"
            "          primary. The poem is on its way there, and a word that will\n"
            "          only be undone later was never the best choice. Where the\n"
            "          finished translation recasts the line and no word of it\n"
            "          answers to this one, choose on your own judgement."
        )

    def strip_synonyms_from_function_words(self, response: Dict) -> Dict:
        """
        Drop the synonyms of a word that has no real ones

        Args:
            response: Parsed word translation response

        Returns:
            The response, with function words left holding a single translation
        """
        part_of_speech = str(response.get('part_of_speech', '')).strip().lower()

        if part_of_speech in FUNCTION_WORD_PARTS_OF_SPEECH and response.get('synonyms'):
            if config.VERBOSE_LOGGING:
                print(
                    f"  · Dropped {len(response['synonyms'])} synonym(s) offered "
                    f"for a {part_of_speech}"
                )
            response['synonyms'] = []

        return response

    def request_block_translation(
        self,
        source_lines: List[str],
        source_language: str,
        target_language: str,
        poem_so_far: str = None,
        whole_poem: str = None,
        mode: str = config.BLOCK_TRANSLATION_MODE_POETIC,
        current_reading: List[str] = None
    ) -> Dict:
        """
        Request translation of a block of the poem, one line at a time

        The block is sent and returned as a list of lines so a block spanning a
        line break comes back with the break in the same place, keeping the
        poem's shape as the blocks grow.

        Args:
            source_lines: The block's source text, one string per line
            source_language: Name of source language
            target_language: Name of target language
            poem_so_far: The poem as it currently reads on screen, so the new
                block fits the words already settled around it
            whole_poem: The complete original poem, for tone and register
            mode: How much licence to take, one of the keys of
                config.BLOCK_TRANSLATION_MODES
            current_reading: How the poem renders this passage right now, one
                string per line. This is what the pass is improving on, and
                leaving it alone is a permitted answer.

        Returns:
            Dictionary with 'lines', a list the same length as source_lines,
            'improvement' saying what the pass bettered, 'unchanged' when it
            found nothing to better, and for the final mode also 'drafts'
        """
        settings = config.BLOCK_TRANSLATION_MODES.get(
            mode, config.BLOCK_TRANSLATION_MODES[config.BLOCK_TRANSLATION_MODE_POETIC]
        )
        is_final = mode == config.BLOCK_TRANSLATION_MODE_FINAL
        is_whole_poem = bool(whole_poem) and '\n'.join(source_lines).strip() == whole_poem.strip()

        line_count = len(source_lines)
        numbered_source = '\n'.join(
            f'{number + 1}. {line}' for number, line in enumerate(source_lines)
        )
        line_placeholders = ', '.join(
            f'"line {number + 1}"' for number in range(line_count)
        )

        prompt = f"""
        {self.describe_block_task(mode, source_language, target_language, line_count)}

        The passage in the original {source_language}, {line_count} line(s):
        {numbered_source}

        {self.describe_current_reading(current_reading)}

        {self.describe_block_context(mode, poem_so_far, whole_poem, is_whole_poem)}

        Return a JSON object with exactly this format:
        {self.describe_block_response_format(settings['draft_count'], line_placeholders)}

        Rules:
        - "lines" must contain exactly {line_count} string(s), one per numbered line above.
        - Keep each line's content on its own line. Do not merge or split lines.
        {self.describe_improvement_rules(current_reading, is_final)}
        {self.describe_block_rules(mode, target_language, settings['draft_count'])}

        Return ONLY the JSON object, no additional text.
        """

        writes_poetry = mode in (
            config.BLOCK_TRANSLATION_MODE_POETIC,
            config.BLOCK_TRANSLATION_MODE_FINAL
        )

        response = self.send_message_to_openai_and_parse_json(
            prompt,
            temperature=settings['temperature'],
            max_tokens=settings['max_tokens'],
            system_prompt=self.build_system_prompt(target_language, poetic=writes_poetry)
        )

        drafts = [draft for draft in response.get('drafts') or [] if isinstance(draft, list)]
        if not response.get('lines') and drafts:
            # The model wrote its drafts but never named a winner.
            response['lines'] = drafts[0]
        response['drafts'] = drafts

        if response.get('unchanged') and current_reading:
            # A pass that found nothing to better says so, and the passage is
            # left exactly as the poem already had it.
            response['lines'] = list(current_reading)

        return response

    def describe_block_task(
        self,
        mode: str,
        source_language: str,
        target_language: str,
        line_count: int
    ) -> str:
        """
        Open the prompt by saying what kind of translation this pass wants

        Args:
            mode: One of the keys of config.BLOCK_TRANSLATION_MODES
            source_language: Name of source language
            target_language: Name of target language
            line_count: Number of lines in the excerpt

        Returns:
            The opening paragraph of the prompt
        """
        if mode == config.BLOCK_TRANSLATION_MODE_FINAL:
            return (
                f"A poem is being translated from {source_language} into "
                f"{target_language}, and this is the last pass. Earlier passes "
                f"worked it out a few words at a time and then reworked it "
                f"passage by passage; what they arrived at is below. Give the "
                f"poem its finished form. This is what the reader is left with, "
                f"so it has to stand on its own as a poem."
            )

        if mode == config.BLOCK_TRANSLATION_MODE_LITERAL:
            return (
                f"A poem is being translated from {source_language} into "
                f"{target_language} a passage at a time, and you are working on "
                f"one short passage of it. It is a fragment, not a complete "
                f"thought. Get its plain sense right and its grammar standing up."
            )

        return (
            f"A poem is being translated from {source_language} into "
            f"{target_language}, passage by passage, and each pass tries to "
            f"leave it better than it found it. You are working on one passage."
        )

    def describe_block_context(
        self,
        mode: str,
        poem_so_far: str = None,
        whole_poem: str = None,
        passage_is_whole_poem: bool = False
    ) -> str:
        """
        Build the context section of the prompt

        Args:
            mode: One of the keys of config.BLOCK_TRANSLATION_MODES
            poem_so_far: The translation as it currently reads on screen
            whole_poem: The complete original poem
            passage_is_whole_poem: Whether the passage being worked on is the
                whole poem, in which case the surroundings are already above
                and repeating them only muddies the prompt

        Returns:
            The context paragraphs, or an empty string
        """
        if passage_is_whole_poem:
            return ''

        sections = []

        if whole_poem:
            sections.append(
                'The passage sits in this poem, given here in the original so '
                f'you can see what surrounds it:\n"""\n{whole_poem}\n"""'
            )

        if poem_so_far:
            sections.append(
                'And this is how the whole poem reads at the moment. Your '
                'passage has to sit inside it, and only your passage is being '
                f'changed:\n"""\n{poem_so_far}\n"""'
            )

        return '\n\n'.join(sections)

    def describe_current_reading(self, current_reading: List[str] = None) -> str:
        """
        Show how the poem renders this passage as things stand

        Args:
            current_reading: The passage as the poem currently has it

        Returns:
            The paragraph holding the current reading, or an empty string
        """
        if not current_reading:
            return ''

        numbered = '\n'.join(
            f'{number + 1}. {line}' for number, line in enumerate(current_reading)
        )
        return f"How the poem renders that passage as it stands:\n        {numbered}"

    def describe_improvement_rules(
        self,
        current_reading: List[str] = None,
        is_final: bool = False
    ) -> str:
        """
        The rules that make a pass an improvement rather than a rewrite

        A pass that translates the source afresh throws away the choices every
        earlier pass made, so the poem churns instead of getting better. These
        rules make the reading on the page the thing being worked on, and make
        leaving it alone an honest answer.

        Args:
            current_reading: The passage as the poem currently has it
            is_final: Whether this is the closing pass, which must produce a
                finished poem and so cannot decline

        Returns:
            Rule lines for the prompt, or an empty string
        """
        if not current_reading:
            return ''

        shared = (
            "- You are not translating from scratch. The reading above is the "
            "work of\n          earlier passes and some of it is already right. "
            "Keep every word that is\n          already the best choice.\n"
            "        - Change only what you can make better, and be able to say "
            "what is better\n          about it: a truer sense, a phrase that "
            "reads as though written rather\n          than translated, a rhythm "
            "closer to the original's, an ending that\n          lands. Changing "
            "a word for a word of the same worth makes the poem\n          "
            "restless, not better.\n"
            "        - Say in \"improvement\", in a few words, what you bettered."
        )

        if is_final:
            return shared

        return (
            f"{shared}\n"
            "        - If the reading above is already the best this passage can "
            "be, set\n          \"unchanged\" to true and repeat it in \"lines\". "
            "Leaving good work alone\n          is a real answer and it is better "
            "than churning it."
        )

    def describe_block_response_format(self, draft_count: int, line_placeholders: str) -> str:
        """
        Describe the JSON shape the model must return

        Args:
            draft_count: How many drafts to ask for
            line_placeholders: Placeholder line strings for the example

        Returns:
            A JSON example for the prompt
        """
        if draft_count <= 1:
            return (
                '{\n'
                f'            "lines": [{line_placeholders}],\n'
                '            "improvement": "what this pass makes better",\n'
                '            "unchanged": false\n'
                '        }'
            )

        return (
            '{\n'
            f'            "drafts": [{", ".join(f"[{line_placeholders}]" for _ in range(draft_count))}],\n'
            f'            "lines": [{line_placeholders}],\n'
            '            "improvement": "what this pass makes better"\n'
            '        }'
        )

    def describe_block_rules(self, mode: str, target_language: str, draft_count: int) -> str:
        """
        Build the rules that differ between passes

        Args:
            mode: One of the keys of config.BLOCK_TRANSLATION_MODES
            target_language: Name of target language
            draft_count: How many drafts were asked for

        Returns:
            The mode's rules as prompt bullet points
        """
        if mode == config.BLOCK_TRANSLATION_MODE_LITERAL:
            return f"""- Make the fragment grammatical {target_language}. Do not complete a
          thought the fragment does not contain, and do not pull in words from
          the rest of the line.
        - Stay close to the wording of the original.
        - Keep the original's punctuation and capitalisation where it carries
          meaning, including question marks, but only if that mark belongs to
          THIS fragment.
        - Read the surrounding context to fit what comes before and after, but
          translate ONLY the excerpt. Your "lines" must cover those words and
          no further.
        - Do not explain, annotate, or add words the poem does not need."""

        shared_poetic_rules = f"""- Write {target_language} that a poet would write. It should read as though
          the poem had been composed in {target_language}, not translated into it.
        - Use natural spoken word order. No inversions or constructions a
          {target_language} speaker would not say, no archaism, no padding.
        - Keep the image and what the poem is doing. You need not keep the
          grammar or the order of the original.
        - Keep a question a question, and keep the poem's address: if the
          original speaks to someone or asks something of them, so must the
          translation."""

        if mode != config.BLOCK_TRANSLATION_MODE_FINAL:
            return f"""{shared_poetic_rules}
        - Read the surrounding context to fit what comes before and after, but
          translate ONLY the excerpt.
        - Do not explain, annotate, or add words the poem does not need."""

        return f"""{shared_poetic_rules}
        - The reading you were given is a working translation, not a sacred
          text. Where it has found the right word, keep it. Where it is weak,
          weigh it against the original and write the line properly.
        - Mind how the poem lands. The last line is what the reader is left
          holding, so it must fall well: end on the word that carries the
          weight, and do not let it trail off or end on a limp preposition or
          auxiliary.
        - Mind the rhythm and the sound. Read each line aloud in your head. No
          line should stumble.
        - Every line must be able to stand as a line of poetry on its own.
        - Write {draft_count} genuinely different drafts of the whole poem in
          "drafts". Vary the phrasing and the shape of the sentences, not just
          the odd word.
        - Then choose the best one and repeat it in "lines". Choose on how it
          sounds read aloud, whether the ending lands, and whether it keeps the
          original's image. Do not explain the choice."""

    def build_system_prompt(self, target_language: str, poetic: bool = False) -> str:
        """
        Build the system message for a request

        Args:
            target_language: Name of target language
            poetic: Whether the pass is writing poetry rather than looking up
                the meaning of a word or fragment

        Returns:
            The system message
        """
        if poetic:
            return (
                f"You are a poet who translates into {target_language}. Your "
                f"translations are read as poems, not as cribs. Always respond "
                f"with valid JSON only."
            )

        return "You are a professional translator. Always respond with valid JSON only."

    def send_message_to_openai_and_parse_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        system_prompt: str = None
    ) -> Dict:
        """
        Send a message to OpenAI API and parse JSON response
        
        Args:
            prompt: The prompt to send to OpenAI
            temperature: How much latitude to allow. Looking up a word wants
                the likeliest answer; writing a poem does not.
            max_tokens: Ceiling on the reply, which has to hold every line of
                every draft in the closing pass
            system_prompt: The system message, defaulting to the translator one
            
        Returns:
            Parsed JSON response as dictionary
            
        Raises:
            ValueError: If response is not valid JSON
            OpenAIError: If the API call fails
        """
        response_text = None

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt or self.build_system_prompt("English")
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                # JSON mode: the model can only emit syntactically valid JSON,
                # so parsing can't fail on prose wrapped around the object.
                response_format={"type": "json_object"}
            )

            response_text = response.choices[0].message.content.strip()
            parsed_json = json.loads(response_text)

            tokens_used = response.usage.total_tokens
            if config.VERBOSE_LOGGING:
                print(f"✓ OpenAI request successful - Tokens used: {tokens_used}")

            return {
                **parsed_json,
                "tokens_used": tokens_used
            }

        except json.JSONDecodeError as error:
            print(f"✗ Failed to parse OpenAI response as JSON: {error}")
            print(f"  Response was: {response_text}")
            raise ValueError(f"Invalid JSON response from OpenAI: {error}")
        except OpenAIError as error:
            print(f"✗ OpenAI API error: {error}")
            raise
        except Exception as error:
            print(f"✗ Unexpected error in OpenAI request: {error}")
            raise

    def validate_word_translation_response(self, response: Dict) -> bool:
        """
        Validate that word translation response has required fields
        
        Args:
            response: Response dictionary from word translation request
            
        Returns:
            True if valid, False otherwise
        """
        required_fields = ['primary_translation', 'synonyms']
        
        if not all(field in response for field in required_fields):
            print(f"✗ Response missing required fields: {required_fields}")
            return False
        
        if not isinstance(response['synonyms'], list):
            print(f"✗ Synonyms must be a list")
            return False
        
        if len(response['synonyms']) > config.MAX_SYNONYMS_PER_WORD:
            print(f"✗ Too many synonyms: {len(response['synonyms'])} > {config.MAX_SYNONYMS_PER_WORD}")
            return False
        
        return True

    def validate_block_translation_response(self, response: Dict) -> bool:
        """
        Validate that a block translation response has usable lines

        A line count that differs from the request is not rejected here; the
        engine redistributes the text across the block's lines instead, since a
        usable translation with the wrong shape beats no translation at all.

        Args:
            response: Response dictionary from block translation request

        Returns:
            True if valid, False otherwise
        """
        if 'lines' not in response:
            print("✗ Response missing required field: lines")
            return False

        if not isinstance(response['lines'], list):
            print("✗ Lines must be a list")
            return False

        if not any(isinstance(line, str) and line.strip() for line in response['lines']):
            print("✗ Lines contained no text")
            return False

        return True
