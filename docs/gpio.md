# GPIO Wiring Guide

This document describes how to wire a momentary push-button to a Raspberry Pi and how the pi_trigger_gpio.py script expects the wiring to be done.

Pin numbering
- Use BCM (Broadcom) GPIO numbering in the examples (e.g., "GPIO17" is BCM 17). This is consistent with gpiozero's default when you pass the number.

Recommended wiring (internal pull-up)
- Default configuration in pi_trigger_gpio.py uses pull_up=True (internal pull-up resistor).
- Wiring:
  - One leg of the momentary push-button -> BCM 17 (GPIO17)
  - Other leg of the push-button -> GND (ground pin)

How it works
- With pull_up=True, the GPIO pin normally reads HIGH. When the button is pressed, it connects the pin to GND and the input reads LOW — the library detects the falling edge/press.

Physical steps
1. Locate pins on the Pi header. Example (Pi 3/4 40-pin header):
   - BCM 17 -> physical pin 11
   - GND -> any ground pin (e.g., physical pin 6)
2. Connect one side of the button to physical pin 11 (BCM 17).
3. Connect the other side of the button to a ground pin.
4. Confirm wiring is secure.

Alternative: external pull-down
- If you prefer wiring the button between 3.3V and the GPIO pin (so pressing connects to 3.3V), use an external pull-down resistor and change the script or set pull_up=False.
- Wiring with external pull-down resistor:
  - Button leg A -> 3.3V
  - Button leg B -> GPIO pin (e.g., BCM 17)
  - Also add a 10k resistor from GPIO pin to GND (pull-down)
  - In script: set Button(BUTTON_PIN, pull_up=False)

Debounce & long-press
- gpiozero's Button handler includes basic debouncing; if you need custom behavior (long-press detection, double-press), extend the script using time and event handlers.

Safety notes
- Always wire to the 3.3V rail; never connect GPIO to 5V — this can permanently damage the Pi.
- Power off the Pi while re-wiring if you're not experienced with Pi GPIO wiring.

Verifying wiring
- Short test in Python REPL (with venv activated and gpiozero installed):
  python3 -c "from gpiozero import Button; b=Button(17); print('Press the button'); b.wait_for_press(); print('Pressed')"
- If it prints "Pressed" when you press the button, wiring and software access to GPIO are good.

If you want, I can add a simple SVG/PNG wiring diagram to the repo illustrating the header pin locations — say "Add wiring graphic" and I’ll prepare one you can commit.