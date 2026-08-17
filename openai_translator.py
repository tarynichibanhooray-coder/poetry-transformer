"""
OpenAI Translator for Poetry Transformer
Handles all AI translation requests with structured JSON output
"""

import json
from typing import List, Dict, Optional
from openai import OpenAI, OpenAIError

import config


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
        target_language: str
    ) -> Dict:
        """
        Request translation of a single word with synonyms from OpenAI
        
        Args:
            source_word: Word to translate
            source_language: Name of source language
            target_language: Name of target language
            
        Returns:
            Dictionary with 'primary_translation' and 'synonyms' (max 7)
        """
        prompt = f"""
        Translate the word "{source_word}" from {source_language} to {target_language}.
        
        Return a JSON object with exactly this format:
        {{
            "primary_translation": "the best translation",
            "synonyms": ["synonym1", "synonym2", "synonym3", "synonym4", "synonym5", "synonym6", "synonym7"]
        }}
        
        Notes:
        - Provide up to 7 synonyms (fewer if fewer alternatives exist)
        - Include the primary translation as the first synonym if applicable
        - All synonyms must be valid alternatives in {target_language}
        - Keep synonyms concise (1-2 words max)
        
        Return ONLY the JSON object, no additional text.
        """
        
        response_data = self.send_message_to_openai_and_parse_json(prompt)
        return response_data

    def request_phrase_translation(
        self,
        source_phrase: str,
        source_language: str,
        target_language: str
    ) -> Dict:
        """
        Request translation of a phrase from OpenAI
        
        Args:
            source_phrase: Phrase to translate
            source_language: Name of source language
            target_language: Name of target language
            
        Returns:
            Dictionary with 'translation'
        """
        prompt = f"""
        Translate the phrase "{source_phrase}" from {source_language} to {target_language}.
        
        Return a JSON object with exactly this format:
        {{
            "translation": "the best translation of the phrase"
        }}
        
        Notes:
        - Preserve the meaning and nuance
        - Keep the translation natural in {target_language}
        - Return ONLY the JSON object, no additional text
        """
        
        response_data = self.send_message_to_openai_and_parse_json(prompt)
        return response_data

    def send_message_to_openai_and_parse_json(self, prompt: str) -> Dict:
        """
        Send a message to OpenAI API and parse JSON response
        
        Args:
            prompt: The prompt to send to OpenAI
            
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
                        "content": "You are a professional translator. Always respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Low temperature for consistency
                max_tokens=500,
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

    def validate_phrase_translation_response(self, response: Dict) -> bool:
        """
        Validate that phrase translation response has required fields
        
        Args:
            response: Response dictionary from phrase translation request
            
        Returns:
            True if valid, False otherwise
        """
        required_fields = ['translation']
        
        if not all(field in response for field in required_fields):
            print(f"✗ Response missing required fields: {required_fields}")
            return False
        
        return True
