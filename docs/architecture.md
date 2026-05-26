# Architecture

The project uses a clear split between real-time firmware and high-level host software.

## Teensy 4.0 firmware responsibilities

- Generate step pulses for the two CoreXY motors.
- Apply CoreXY inverse kinematics.
- Home the carriage using endstops.
- Scan the 64 Hall sensors through four CD74HC4067 multiplexers.
- Control the Z servo using PWM.
- Control the electromagnet through a MOSFET driver.
- Return ACK/NACK and event messages over newline-delimited JSON.

## Python host responsibilities

- Maintain the authoritative chess state using python-chess.
- Turn scan differences into legal chess moves.
- Ask Stockfish for engine moves.
- Send physical move commands to the Teensy 4.0.
- Store games/calibration in SQLite through SQLModel.
- Serve a local FastAPI/Jinja/WebSocket UI.
