"""
Main Entry Point for Poetry Transformer
Orchestrates all components and handles the main application loop
"""

import sys
from pathlib import Path

import config
from database_manager import DatabaseManager
from openai_translator import OpenAITranslator
from motion_sensor_handler import MotionSensorHandler
from poem_transformer_engine import PoemTransformerEngine, TransformationPhase
from display_renderer import DisplayRenderer


class PoetryTransformerApplication:
    """Main application class that orchestrates all components"""

    def __init__(self):
        """Initialize the Poetry Transformer application"""
        self.database_manager = DatabaseManager()
        self.ai_translator = OpenAITranslator()
        self.transformer_engine = PoemTransformerEngine()
        self.display_renderer = DisplayRenderer()
        self.sensor_handler = None
        
        if config.DEBUG_MODE:
            print("\n" + "="*80)
            print("POETRY TRANSFORMER - INITIALIZATION")
            print("="*80)

    def initialize_application_components(self) -> None:
        """Initialize all application components"""
        try:
            # Load the poem
            self.load_poem_and_initialize_transformer()
            
            # Set up motion sensor with callback
            self.setup_motion_sensor_with_trigger_callback()
            
            if config.DEBUG_MODE:
                print("✓ All components initialized successfully")
                self.print_startup_summary()
                
        except Exception as error:
            print(f"✗ Failed to initialize application: {error}")
            raise

    def load_poem_and_initialize_transformer(self) -> None:
        """
        Load the most recently saved poem, falling back to the poem file

        Poems added through the web UI are stored with the language they were
        written in, so the database is the better source. The file is kept as a
        fallback for a fresh install with nothing saved yet.
        """
        saved_poems = self.database_manager.retrieve_all_poem_entries()

        if saved_poems:
            poem = saved_poems[0]
            self.transformer_engine.initialize_poem_with_text(
                poem['raw_text'],
                source_language=poem['source_language'],
                source_language_code=poem['source_language_code'],
                target_language=poem['target_language'],
                target_language_code=poem['target_language_code']
            )
            poem_label = poem['title'] or f"untitled #{poem['id']}"
            print(f"✓ Poem loaded from database: {poem_label}")
            return

        poem_path = config.POEM_FILE_PATH

        if not poem_path.exists():
            raise FileNotFoundError(
                f"No saved poems and no poem file at {poem_path}. "
                f"Add a poem at /add.html or create that file."
            )

        self.transformer_engine.load_poem_from_file(str(poem_path))
        print(f"✓ Poem loaded from file: {poem_path}")

    def setup_motion_sensor_with_trigger_callback(self) -> None:
        """Set up motion sensor with transformation callback"""
        self.sensor_handler = MotionSensorHandler(
            gpio_pin=config.MOTION_SENSOR_GPIO_PIN,
            debounce_seconds=config.MOTION_SENSOR_DEBOUNCE_SECONDS,
            trigger_callback=self.handle_sensor_trigger_advance_transformation
        )
        
        self.sensor_handler.start_listening_for_sensor_triggers()
        print(f"✓ Motion sensor listening on GPIO {config.MOTION_SENSOR_GPIO_PIN}")

    def handle_sensor_trigger_advance_transformation(self) -> None:
        """
        Callback function for sensor triggers
        Advances the transformation and renders output
        """
        try:
            # Process trigger and get new transformation state
            new_poem_state = self.transformer_engine.process_next_sensor_trigger()
            
            # Get statistics for display
            stats = self.transformer_engine.get_transformation_statistics()
            
            # Render the current state
            self.display_renderer.render_transformed_poem_to_output(
                new_poem_state,
                metadata=stats
            )
            
            # Check if transformation is complete
            if self.transformer_engine.get_current_phase() == TransformationPhase.COMPLETE:
                print("\n✓ TRANSFORMATION COMPLETE!")
                self.display_final_transformation_summary()
                
        except Exception as error:
            print(f"✗ Error processing trigger: {error}")

    def print_startup_summary(self) -> None:
        """Print startup summary information"""
        print("\n" + "-"*80)
        print("TRANSFORMATION CONFIGURATION:")
        print(f"  Source Language: {self.transformer_engine.source_language}")
        print(f"  Target Language: {self.transformer_engine.target_language}")
        print(f"  Output Mode: {config.DISPLAY_OUTPUT_MODE}")
        print(f"  Poem Words: {len(self.transformer_engine.original_poem_words)}")
        print("-"*80 + "\n")

    def display_final_transformation_summary(self) -> None:
        """Display summary of completed transformation"""
        stats = self.transformer_engine.get_transformation_statistics()
        
        self.display_renderer.print_statistics_display_to_console(
            stats['trigger_count'],
            stats['current_phase'],
            stats['total_words'],
            stats['cached_words'],
            stats['cached_phrases'],
            stats['api_requests'],
            stats['total_tokens_used']
        )

    def run_application_main_loop(self) -> None:
        """
        Run the main application loop
        Listens for sensor triggers and processes transformations
        """
        try:
            if config.DEBUG_MODE:
                print("\n" + "="*80)
                print("APPLICATION RUNNING - Listening for sensor triggers")
                print("Press Ctrl+C to exit")
                print("="*80 + "\n")
            
            # Keep the application running
            import time
            while True:
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n\n✓ Application stopped by user")
            self.shutdown_application_gracefully()

    def shutdown_application_gracefully(self) -> None:
        """Shutdown application and clean up resources"""
        try:
            if self.sensor_handler:
                self.sensor_handler.stop_listening_for_sensor_triggers()
            
            if self.database_manager:
                self.database_manager.close_database_connection()
            
            if config.DEBUG_MODE:
                print("✓ Application shutdown complete")
                
        except Exception as error:
            print(f"✗ Error during shutdown: {error}")

    def run_simulation_mode_for_testing(self, trigger_count: int = 5) -> None:
        """
        Run application in simulation mode for testing without hardware
        
        Args:
            trigger_count: Number of simulated triggers to process
        """
        print(f"\n{'='*80}")
        print(f"SIMULATION MODE - {trigger_count} simulated triggers")
        print(f"{'='*80}\n")
        
        try:
            for i in range(trigger_count):
                print(f"\n--- Simulated Trigger #{i+1} ---")
                
                # Simulate sensor trigger
                new_poem_state = self.transformer_engine.process_next_sensor_trigger()
                
                # Get statistics
                stats = self.transformer_engine.get_transformation_statistics()
                
                # Display
                self.display_renderer.render_transformed_poem_to_output(
                    new_poem_state,
                    metadata=stats
                )
                
                # Print progress
                self.display_renderer.print_progress_bar_to_console(
                    stats['progress_percentage'],
                    stats['trigger_count'],
                    stats['current_phase']
                )
                
                # Check completion
                if self.transformer_engine.get_current_phase() == TransformationPhase.COMPLETE:
                    print("\n✓ TRANSFORMATION COMPLETE!")
                    break
            
            self.display_final_transformation_summary()
            
        except Exception as error:
            print(f"✗ Error in simulation: {error}")
        finally:
            self.shutdown_application_gracefully()


def main():
    """
    Main entry point for the Poetry Transformer application
    """
    try:
        # Create application
        app = PoetryTransformerApplication()
        
        # Initialize components
        app.initialize_application_components()
        
        # Check if running in simulation mode (useful for testing)
        if len(sys.argv) > 1 and sys.argv[1] == "--simulate":
            # Run simulation with optional trigger count
            trigger_count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            app.run_simulation_mode_for_testing(trigger_count)
        else:
            # Run normal mode with sensor listening
            app.run_application_main_loop()
        
    except Exception as error:
        print(f"\n✗ FATAL ERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
