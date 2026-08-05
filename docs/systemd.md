# systemd service for Raspberry Pi (pi-trigger-gpio and server)

This document explains the example systemd unit files included in the repo and how to install and configure them on a Raspberry Pi.

Files in the repository
- systemd/pi-trigger-gpio.service — example unit for the GPIO trigger client (pi_trigger_gpio.py)
- (README includes a poetry-transformer.service example for the server)

Install the pi-trigger-gpio service
1. Copy the example unit to systemd:

   sudo cp systemd/pi-trigger-gpio.service /etc/systemd/system/pi-trigger-gpio.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now pi-trigger-gpio

2. Verify status & logs:

   sudo systemctl status pi-trigger-gpio
   sudo journalctl -u pi-trigger-gpio -f

Environment variables in the unit
- The example unit includes Environment= lines for SERVER_URL, PI_RETRY_INTERVAL, and BUTTON_PIN.
- To customize these without editing the unit file directly, use systemctl edit to create an override file:

   sudo systemctl edit --full pi-trigger-gpio
   # edit the Environment= lines or add new ones
   sudo systemctl daemon-reload
   sudo systemctl restart pi-trigger-gpio

Running in a venv
- The example unit executes the script using the repo venv at /home/pi/poetry-transformer/.venv/bin/python.
- If you used a different path for your venv, update ExecStart accordingly.

Service permissions and user
- The example runs as `User=pi`. This user typically has access to GPIO when using gpiozero. If you run as a different user, ensure they have necessary permissions.

poetry-transformer server unit (example)
- If you host the FastAPI server on the Pi, create a unit like this (example shown in README):

  [Unit]
  Description=Poetry Transformer FastAPI server
  After=network.target

  [Service]
  Type=simple
  User=pi
  WorkingDirectory=/home/pi/poetry-transformer
  ExecStart=/home/pi/poetry-transformer/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
  Restart=on-failure

  [Install]
  WantedBy=multi-user.target

- Install, enable, and start the server unit the same way as the GPIO service.

Troubleshooting
- If the service immediately exits or fails to start:
  - Check ExecStart path and WorkingDirectory.
  - Ensure the python binary and deps are installed in the venv.
  - Check journalctl for error traces (missing modules, permission errors).

Log files & runtime files
- pi_trigger_gpio.py writes no files except `pi_queue.jsonl` (in the repo directory) when queued triggers exist.
- The server writes events to output/translation_stream.jsonl — check this file to confirm the server processed triggers.

Updating the unit file safely
- Use systemctl edit --full to avoid losing manual local edits when pulling upstream changes.

If you want, I can also add a small install script (scripts/install-pi-service.sh) that copies the unit, runs daemon-reload, and enables the service — say "Add install script."