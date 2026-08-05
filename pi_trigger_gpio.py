#!/usr/bin/env python3
"""
pi_trigger_gpio.py
GPIO-driven Raspberry Pi trigger client for headless operation.

- Listens to a physical button on a GPIO pin and POSTs to SERVER_URL/trigger when pressed.
- If the POST fails, appends the payload to a local queue file and retries in the background.

Environment variables:
- SERVER_URL (default: http://localhost:8000)
- PI_RETRY_INTERVAL (seconds between retry attempts, default: 10)
- BUTTON_PIN (BCM pin number to use for the button, default: 17)

Usage:
- Install dependencies in your venv: pip install -r requirements.txt gpiozero
- Ensure the service's WorkingDirectory is the repo directory so the queue file is stored there.
"""
import os
import time
import json
import threading
from pathlib import Path

import requests
from gpiozero import Button

# Configuration from environment
SERVER_URL = os.environ.get('SERVER_URL', 'http://localhost:8000')
TRIGGER_ENDPOINT = SERVER_URL.rstrip('/') + '/trigger'
RETRY_INTERVAL = int(os.environ.get('PI_RETRY_INTERVAL', '10'))
BUTTON_PIN = int(os.environ.get('BUTTON_PIN', '17'))  # BCM pin

BASE_DIR = Path(__file__).resolve().parent
QUEUE_FILE = BASE_DIR / 'pi_queue.jsonl'


def append_to_queue(payload: dict):
    try:
        with QUEUE_FILE.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
        print('Appended payload to queue')
    except Exception as e:
        print(f'Failed to append to queue: {e}')


def flush_queue_once():
    if not QUEUE_FILE.exists():
        return
    try:
        with QUEUE_FILE.open('r', encoding='utf-8') as fh:
            lines = fh.read().splitlines()
    except Exception as e:
        print(f'Failed to read queue file: {e}')
        return

    if not lines:
        return

    remaining = []
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            # malformed line, skip
            continue
        try:
            resp = requests.post(TRIGGER_ENDPOINT, json=payload, timeout=5)
            if 200 <= resp.status_code < 300:
                print('Flushed queued trigger')
            else:
                print(f'Queued trigger failed with status {resp.status_code}')
                remaining.append(line)
        except Exception as e:
            print(f'Failed to send queued trigger: {e}')
            remaining.append(line)

    # overwrite queue file with remaining
    try:
        if remaining:
            with QUEUE_FILE.open('w', encoding='utf-8') as fh:
                fh.write('\n'.join(remaining) + '\n')
        else:
            QUEUE_FILE.unlink()
    except Exception as e:
        print(f'Failed to update queue file: {e}')


def queue_flusher_loop():
    while True:
        try:
            flush_queue_once()
        except Exception as e:
            print(f'Queue flusher error: {e}')
        time.sleep(RETRY_INTERVAL)


def try_send_trigger(payload: dict) -> bool:
    try:
        resp = requests.post(TRIGGER_ENDPOINT, json=payload, timeout=5)
        if 200 <= resp.status_code < 300:
            print('Trigger sent successfully')
            return True
        else:
            print(f'Trigger failed: {resp.status_code} {resp.text}')
            return False
    except Exception as e:
        print(f'Trigger request error: {e}')
        return False


def on_button_pressed():
    payload = {"triggered_by": "pi_gpio", "timestamp": int(time.time())}
    ok = try_send_trigger(payload)
    if not ok:
        append_to_queue(payload)
        print('Queued trigger for retry')


def main():
    # Start queue flusher thread
    thread = threading.Thread(target=queue_flusher_loop, daemon=True)
    thread.start()

    # Setup GPIO button
    btn = Button(BUTTON_PIN, pull_up=True)
    btn.when_pressed = on_button_pressed

    print(f'GPIO trigger service running. Button pin={BUTTON_PIN}. Posting to {TRIGGER_ENDPOINT}')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('Exiting')


if __name__ == '__main__':
    main()
