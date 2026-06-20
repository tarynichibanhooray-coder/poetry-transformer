"""
Motion Sensor Handler for Poetry Transformer
Handles GPIO sensor input with debouncing and flexible trigger abstraction
"""

from typing import Callable, Optional
from datetime import datetime, timedelta
import time

import config


class MotionSensorHandler:
    """Manages motion sensor input with debouncing and trigger callbacks"""

    def __init__(
        self,
        gpio_pin: int = None,
        debounce_seconds: float = None,
        trigger_callback: Callable = None
    ):
        """
        Initialize motion sensor handler
        
        Args:
            gpio_pin: GPIO pin number (BCM) for sensor
            debounce_seconds: Debounce time to prevent false triggers
            trigger_callback: Function to call when sensor triggers
        """
        self.gpio_pin = gpio_pin or config.MOTION_SENSOR_GPIO_PIN
        self.debounce_seconds = debounce_seconds or config.MOTION_SENSOR_DEBOUNCE_SECONDS
        self.trigger_callback = trigger_callback
        
        self.last_trigger_time = None
        self.is_listening = False
        self.trigger_count = 0
        
        self.initialize_gpio_for_sensor()
        if config.DEBUG_MODE:
            print(f"✓ Motion Sensor Handler initialized on GPIO pin {self.gpio_pin}")

    def initialize_gpio_for_sensor(self) -> None:
        """
        Initialize GPIO pins for motion sensor input
        Sets up the GPIO library and configures pin as input
        """
        try:
            import RPi.GPIO as GPIO
            
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.IN)
            
            if config.DEBUG_MODE:
                print(f"✓ GPIO pin {self.gpio_pin} configured as input")
                
        except ImportError:
            print("⚠ RPi.GPIO not available - using simulation mode")
            print("  (For testing without Raspberry Pi hardware)")
        except RuntimeError as error:
            print(f"✗ GPIO initialization failed: {error}")
            print("  Make sure this script runs with appropriate permissions")
            raise

    def register_trigger_callback_function(self, callback: Callable) -> None:
        """
        Register a callback function to be called when sensor triggers
        
        Args:
            callback: Function to call on trigger (should accept no args)
        """
        self.trigger_callback = callback
        if config.DEBUG_MODE:
            print(f"✓ Trigger callback registered: {callback.__name__}")

    def start_listening_for_sensor_triggers(self) -> None:
        """
        Start listening for motion sensor triggers
        Sets up event detection on GPIO pin
        """
        try:
            import RPi.GPIO as GPIO
            
            GPIO.add_event_detect(
                self.gpio_pin,
                GPIO.RISING,
                callback=self.handle_sensor_trigger_event,
                bouncetime=int(self.debounce_seconds * 1000)
            )
            
            self.is_listening = True
            if config.DEBUG_MODE:
                print(f"✓ Listening for motion sensor triggers on GPIO {self.gpio_pin}")
                
        except ImportError:
            print("⚠ GPIO event detection not available - using polling mode")
        except Exception as error:
            print(f"✗ Failed to start listening: {error}")
            raise

    def stop_listening_for_sensor_triggers(self) -> None:
        """
        Stop listening for motion sensor triggers
        Removes event detection and cleans up GPIO
        """
        try:
            import RPi.GPIO as GPIO
            
            GPIO.remove_event_detect(self.gpio_pin)
            GPIO.cleanup(self.gpio_pin)
            
            self.is_listening = False
            if config.DEBUG_MODE:
                print(f"✓ Stopped listening for motion sensor triggers")
                
        except ImportError:
            pass
        except Exception as error:
            print(f"✗ Failed to stop listening: {error}")

    def handle_sensor_trigger_event(self, channel: int) -> None:
        """
        Handle motion sensor trigger event (called by GPIO interrupt)
        
        Args:
            channel: GPIO channel that triggered
        """
        # Check debounce timing
        if not self.is_trigger_within_debounce_window():
            self.process_valid_sensor_trigger()

    def is_trigger_within_debounce_window(self) -> bool:
        """
        Check if trigger is too soon after last trigger (debounce)
        
        Returns:
            True if trigger is within debounce window, False otherwise
        """
        if self.last_trigger_time is None:
            return False
        
        time_since_last_trigger = datetime.now() - self.last_trigger_time
        debounce_window = timedelta(seconds=self.debounce_seconds)
        
        return time_since_last_trigger < debounce_window

    def process_valid_sensor_trigger(self) -> None:
        """
        Process a valid sensor trigger that passed debounce check
        Updates timing and calls registered callback
        """
        self.last_trigger_time = datetime.now()
        self.trigger_count += 1
        
        if config.DEBUG_MODE:
            print(f"✓ Motion sensor triggered (count: {self.trigger_count})")
        
        if self.trigger_callback:
            try:
                self.trigger_callback()
            except Exception as error:
                print(f"✗ Error in trigger callback: {error}")

    def simulate_sensor_trigger_for_testing(self) -> None:
        """
        Simulate a sensor trigger for testing without physical sensor
        Useful for development and debugging
        """
        if not self.is_trigger_within_debounce_window():
            self.process_valid_sensor_trigger()
        else:
            print("⚠ Trigger ignored - within debounce window")

    def get_total_trigger_count(self) -> int:
        """
        Get total number of triggers since startup
        
        Returns:
            Total trigger count
        """
        return self.trigger_count

    def get_time_since_last_trigger(self) -> Optional[float]:
        """
        Get seconds elapsed since last trigger
        
        Returns:
            Seconds since last trigger, or None if never triggered
        """
        if self.last_trigger_time is None:
            return None
        
        return (datetime.now() - self.last_trigger_time).total_seconds()

    def reset_trigger_counter(self) -> None:
        """
        Reset the trigger counter to zero
        """
        self.trigger_count = 0
        if config.DEBUG_MODE:
            print("✓ Trigger counter reset to 0")

    def get_sensor_status_summary(self) -> dict:
        """
        Get a summary of sensor status
        
        Returns:
            Dictionary with sensor status information
        """
        return {
            "gpio_pin": self.gpio_pin,
            "is_listening": self.is_listening,
            "trigger_count": self.trigger_count,
            "debounce_seconds": self.debounce_seconds,
            "time_since_last_trigger": self.get_time_since_last_trigger(),
            "last_trigger_time": self.last_trigger_time
        }
