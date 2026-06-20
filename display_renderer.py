"""
Display Renderer for Poetry Transformer
Handles output rendering to console, file, or custom formats
"""

from typing import Optional
from pathlib import Path
from datetime import datetime

import config


class DisplayRenderer:
    """Manages rendering and output of the transforming poem"""

    def __init__(self, output_mode: str = None):
        """
        Initialize display renderer
        
        Args:
            output_mode: 'console', 'file', or 'custom'
        """
        self.output_mode = output_mode or config.DISPLAY_OUTPUT_MODE
        self.output_file_path = config.DISPLAY_OUTPUT_FILE_PATH
        self.render_history = []
        
        if config.DEBUG_MODE:
            print(f"✓ Display Renderer initialized with mode: {self.output_mode}")

    def render_transformed_poem_to_output(self, poem_text: str, metadata: dict = None) -> None:
        """
        Render the transformed poem to the configured output destination
        
        Args:
            poem_text: The poem text to render
            metadata: Optional metadata about the transformation
        """
        if self.output_mode == "console":
            self.render_poem_to_console_output(poem_text, metadata)
        elif self.output_mode == "file":
            self.render_poem_to_file_output(poem_text, metadata)
        elif self.output_mode == "custom":
            self.render_poem_to_custom_format_output(poem_text, metadata)
        
        # Record in history
        self.render_history.append({
            "timestamp": datetime.now(),
            "mode": self.output_mode,
            "poem_length": len(poem_text),
            "metadata": metadata
        })

    def render_poem_to_console_output(self, poem_text: str, metadata: dict = None) -> None:
        """
        Render poem to console (stdout)
        
        Args:
            poem_text: The poem text to display
            metadata: Optional metadata to display
        """
        print("\n" + "="*80)
        print("TRANSFORMED POEM")
        print("="*80)
        print(poem_text)
        print("="*80)
        
        if metadata:
            self.print_metadata_to_console(metadata)
        
        print()

    def render_poem_to_file_output(self, poem_text: str, metadata: dict = None) -> None:
        """
        Render poem to text file
        
        Args:
            poem_text: The poem text to write
            metadata: Optional metadata to include
        """
        try:
            # Ensure output directory exists
            self.output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.output_file_path, 'w', encoding='utf-8') as file:
                file.write("TRANSFORMED POEM\n")
                file.write("="*80 + "\n\n")
                file.write(poem_text)
                file.write("\n\n" + "="*80 + "\n")
                
                if metadata:
                    file.write(self.format_metadata_as_text(metadata))
            
            if config.DEBUG_MODE:
                print(f"✓ Poem rendered to file: {self.output_file_path}")
                
        except IOError as error:
            print(f"✗ Failed to write to file: {error}")

    def render_poem_to_custom_format_output(self, poem_text: str, metadata: dict = None) -> None:
        """
        Render poem to custom format (suitable for web/screen projection)
        
        Args:
            poem_text: The poem text
            metadata: Optional metadata
        """
        # Create a custom format suitable for animation/projection
        custom_output = {
            "type": "poem_render",
            "timestamp": datetime.now().isoformat(),
            "content": poem_text,
            "line_count": len(poem_text.split('\n')),
            "word_count": len(poem_text.split()),
            "metadata": metadata or {}
        }
        
        # Output as formatted JSON
        import json
        print(json.dumps(custom_output, indent=2, ensure_ascii=False))

    def print_metadata_to_console(self, metadata: dict) -> None:
        """
        Print transformation metadata to console
        
        Args:
            metadata: Metadata dictionary
        """
        print("\nMETADATA:")
        print("-" * 80)
        for key, value in metadata.items():
            if isinstance(value, (int, float)):
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")
        print("-" * 80)

    def format_metadata_as_text(self, metadata: dict) -> str:
        """
        Format metadata as readable text
        
        Args:
            metadata: Metadata dictionary
            
        Returns:
            Formatted metadata as string
        """
        lines = ["\nMETADATA:", "-" * 80]
        
        for key, value in metadata.items():
            if isinstance(value, (int, float)):
                lines.append(f"  {key}: {value}")
            else:
                lines.append(f"  {key}: {value}")
        
        lines.append("-" * 80)
        return "\n".join(lines)

    def render_transformation_progress_bar(
        self,
        progress_percentage: float,
        bar_width: int = 40
    ) -> str:
        """
        Render a text-based progress bar for transformation
        
        Args:
            progress_percentage: Progress as percentage (0-100)
            bar_width: Width of progress bar in characters
            
        Returns:
            Formatted progress bar string
        """
        filled_width = int((progress_percentage / 100) * bar_width)
        empty_width = bar_width - filled_width
        
        bar = "█" * filled_width + "░" * empty_width
        percentage_str = f"{progress_percentage:.1f}%"
        
        return f"[{bar}] {percentage_str}"

    def print_progress_bar_to_console(
        self,
        progress_percentage: float,
        trigger_count: int = None,
        phase_name: str = None
    ) -> None:
        """
        Print progress bar to console with optional context
        
        Args:
            progress_percentage: Progress as percentage (0-100)
            trigger_count: Optional number of triggers so far
            phase_name: Optional current phase name
        """
        progress_bar = self.render_transformation_progress_bar(progress_percentage)
        print(f"\n{progress_bar}", end="")
        
        if trigger_count is not None:
            print(f" [Trigger #{trigger_count}]", end="")
        
        if phase_name is not None:
            print(f" [{phase_name}]", end="")
        
        print()

    def render_side_by_side_comparison(
        self,
        original_poem: str,
        current_state: str,
        target_language: str
    ) -> str:
        """
        Create a side-by-side comparison of original and transformed poem
        
        Args:
            original_poem: The original poem text
            current_state: The current transformation state
            target_language: Name of target language
            
        Returns:
            Formatted comparison string
        """
        original_lines = original_poem.split('\n')
        current_lines = current_state.split('\n')
        
        # Pad lines to same length
        max_lines = max(len(original_lines), len(current_lines))
        original_lines.extend([''] * (max_lines - len(original_lines)))
        current_lines.extend([''] * (max_lines - len(current_lines)))
        
        comparison_lines = [
            "TRANSFORMATION COMPARISON",
            "=" * 100,
            f"{'ORIGINAL':<48} | {'TRANSFORMING TO ' + target_language:<48}",
            "-" * 100
        ]
        
        for orig, curr in zip(original_lines, current_lines):
            comparison_lines.append(f"{orig:<48} | {curr:<48}")
        
        comparison_lines.append("=" * 100)
        
        return "\n".join(comparison_lines)

    def print_side_by_side_comparison_to_console(
        self,
        original_poem: str,
        current_state: str,
        target_language: str
    ) -> None:
        """
        Print side-by-side comparison to console
        
        Args:
            original_poem: The original poem text
            current_state: The current transformation state
            target_language: Name of target language
        """
        comparison = self.render_side_by_side_comparison(
            original_poem,
            current_state,
            target_language
        )
        print(comparison)

    def render_phase_transition_message(self, new_phase_name: str) -> str:
        """
        Create a formatted message for phase transition
        
        Args:
            new_phase_name: Name of new phase
            
        Returns:
            Formatted phase transition message
        """
        return (
            f"\n{'*' * 80}\n"
            f"PHASE TRANSITION: Advancing to {new_phase_name}\n"
            f"{'*' * 80}\n"
        )

    def print_phase_transition_message_to_console(self, new_phase_name: str) -> None:
        """
        Print phase transition message to console
        
        Args:
            new_phase_name: Name of new phase
        """
        message = self.render_phase_transition_message(new_phase_name)
        print(message)

    def render_statistics_display(
        self,
        trigger_count: int,
        current_phase: str,
        total_words: int,
        cached_words: int,
        cached_phrases: int,
        api_requests: int,
        tokens_used: int
    ) -> str:
        """
        Create formatted statistics display
        
        Args:
            trigger_count: Number of triggers processed
            current_phase: Current transformation phase
            total_words: Total words in poem
            cached_words: Number of cached word translations
            cached_phrases: Number of cached phrase translations
            api_requests: Total API requests made
            tokens_used: Total tokens consumed
            
        Returns:
            Formatted statistics string
        """
        stats_lines = [
            "\nTRANSFORMATION STATISTICS",
            "=" * 60,
            f"  Trigger Count: {trigger_count}",
            f"  Current Phase: {current_phase}",
            f"  Total Words: {total_words}",
            f"  Cached Words: {cached_words}",
            f"  Cached Phrases: {cached_phrases}",
            f"  API Requests: {api_requests}",
            f"  Total Tokens Used: {tokens_used}",
            "=" * 60
        ]
        
        return "\n".join(stats_lines)

    def print_statistics_display_to_console(
        self,
        trigger_count: int,
        current_phase: str,
        total_words: int,
        cached_words: int,
        cached_phrases: int,
        api_requests: int,
        tokens_used: int
    ) -> None:
        """
        Print statistics display to console
        
        Args:
            trigger_count: Number of triggers processed
            current_phase: Current transformation phase
            total_words: Total words in poem
            cached_words: Number of cached word translations
            cached_phrases: Number of cached phrase translations
            api_requests: Total API requests made
            tokens_used: Total tokens consumed
        """
        stats = self.render_statistics_display(
            trigger_count,
            current_phase,
            total_words,
            cached_words,
            cached_phrases,
            api_requests,
            tokens_used
        )
        print(stats)

    def get_render_history_count(self) -> int:
        """
        Get number of renders performed
        
        Returns:
            Number of renders in history
        """
        return len(self.render_history)

    def clear_render_history(self) -> None:
        """Clear the render history"""
        self.render_history = []
        if config.DEBUG_MODE:
            print("✓ Render history cleared")
