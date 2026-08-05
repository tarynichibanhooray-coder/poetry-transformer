#!/usr/bin/env python3
"""
pi_trigger.py
Simple Raspberry Pi trigger client that posts to /trigger on spacebar press.
If the Pi is running the server locally, set SERVER_URL to http://localhost:8000
"""
import os
import requests
import sys
import termios
import tty

SERVER_URL = os.environ.get('SERVER_URL', 'http://localhost:8000')
TRIGGER_ENDPOINT = SERVER_URL.rstrip('/') + '/trigger'


def getch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


print(f"Pi trigger client. Press SPACE to send a trigger to {TRIGGER_ENDPOINT}. Press 'q' to quit.")
while True:
    ch = getch()
    if ch == 'q':
        print('Quitting.')
        break
    if ch == ' ':
        try:
            resp = requests.post(TRIGGER_ENDPOINT, timeout=5)
            print(f"Triggered: {resp.status_code}")
        except Exception as e:
            print(f"Failed to send trigger: {e}")
