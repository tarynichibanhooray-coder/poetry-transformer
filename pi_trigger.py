#!/usr/bin/env python3
"""
pi_trigger.py
Simple Raspberry Pi trigger client that posts to /trigger on spacebar press and queues failed attempts to disk.

Behavior:
- When SPACE is pressed, attempt POST to SERVER_URL/trigger.
- On failure, append a queued event to pi_queue.jsonl.
- Background thread flushes pi_queue.jsonl every RETRY_INTERVAL seconds and removes items that succeed.
"""
import os
import requests
import sys
import termios
import tty
import threading
import time
import json
from pathlib import Path

SERVER_URL = os.environ.get('SERVER_URL', 'http://localhost:8000')
TRIGGER_ENDPOINT = SERVER_URL.rstrip('/') + '/trigger'
QUEUE_FILE = Path('pi_queue.jsonl')
RETRY_INTERVAL = int(os.environ.get('PI_RETRY_INTERVAL', '10'))  # seconds


def getch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def append_to_queue(payload: dict):
    try:
        with QUEUE_FILE.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"Failed to append to queue: {e}")


def flush_queue_once():
    if not QUEUE_FILE.exists():
        return
    try:
        with QUEUE_FILE.open('r', encoding='utf-8') as fh:
            lines = fh.read().splitlines()
    except Exception as e:
        print(f"Failed to read queue file: {e}")
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
                print("Flushed queued trigger")
            else:
                print(f"Queued trigger failed with status {resp.status_code}")
                remaining.append(line)
        except Exception as e:
            print(f"Failed to send queued trigger: {e}")
            remaining.append(line)

    # overwrite queue file with remaining
    try:
        if remaining:
            with QUEUE_FILE.open('w', encoding='utf-8') as fh:
                fh.write('\n'.join(remaining) + '\n')
        else:
            QUEUE_FILE.unlink()
    except Exception as e:
        print(f"Failed to update queue file: {e}")


def queue_flusher_loop():
    while True:
        try:
            flush_queue_once()
        except Exception as e:
            print(f"Queue flusher error: {e}")
        time.sleep(RETRY_INTERVAL)


def try_send_trigger(payload: dict) -> bool:
    try:
        resp = requests.post(TRIGGER_ENDPOINT, json=payload, timeout=5)
        if 200 <= resp.status_code < 300:
            print("Trigger sent successfully")
            return True
        else:
            print(f"Trigger failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"Trigger request error: {e}")
        return False


def main():
    # start flusher thread
    thread = threading.Thread(target=queue_flusher_loop, daemon=True)
    thread.start()

    print(f"Pi trigger client. Press SPACE to send a trigger to {TRIGGER_ENDPOINT}. Press 'q' to quit.")
    while True:
        ch = getch()
        if ch == 'q':
            print('Quitting.')
            break
        if ch == ' ':
            payload = {"triggered_by": "pi", "timestamp": int(time.time())}
            ok = try_send_trigger(payload)
            if not ok:
                append_to_queue(payload)
                print("Queued trigger for retry")


if __name__ == '__main__':
    main()
