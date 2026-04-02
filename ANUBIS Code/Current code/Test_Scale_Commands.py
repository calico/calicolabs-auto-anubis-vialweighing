# -*- coding: utf-8 -*-
"""
A hands-free Python script to manually control a Mettler Toledo scale
and log weights via a command-line interface. This version allows sending
raw commands directly to the scale.

When stopped, this script can format the collected data into a structured
CSV file suitable for printing.

Required Library:
- pySerial: Install using pip: pip install pyserial
"""
import serial
import time
import csv
from datetime import datetime
import os

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from hardware.scale import MettlerToledoController
def write_formatted_csv(filename, collected_weights):
    """Writes the collected weights into the specified two-column grid format."""
    if not collected_weights:
        print("No weights were logged, so no file was created.")
        return
    print(f"\nFormatting and writing {len(collected_weights)} readings to {filename}...")
    try:
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            today_date = datetime.now().strftime('%Y-%m-%d')
            writer.writerow([today_date])
            writer.writerow(['Cell', 'Weight'])
            for i, weight_value in enumerate(collected_weights):
                # Assumes a 6-column layout (A-F) for cell labeling
                row_number = (i // 6) + 1
                col_letter = chr(ord('A') + (i % 6))
                cell_label = f"{col_letter}{row_number}"
                writer.writerow([cell_label, weight_value])
        print(f"Formatted CSV file '{filename}' has been saved successfully.")
    except IOError as e:
        print(f"Error: Could not write to {filename}. Details: {e}")

def print_help():
    """Prints the list of available commands."""
    print("\n--- Mettler Toledo Interactive Controller ---")
    print("Available commands:")
    print("  connect      - Connect to the scale")
    print("  disconnect   - Disconnect from the scale")
    print("  reset        - Wake the scale from standby")
    print("  open         - Open draft shield doors")
    print("  close        - Close draft shield doors")
    print("  zero         - Zero the scale")
    print("  stable       - Get a stable weight reading")
    print("  now          - Get an immediate weight reading")
    print("  log          - Get a stable weight and log it for the final report")
    print("  show         - Show all weights logged in this session")
    print("  save         - Save logged weights to the CSV file")
    print("  send <cmd>   - Send a raw command to the scale (e.g., 'send DW')")
    print("  help         - Show this list of commands")
    print("  exit         - Save logs, disconnect, and close the program")
    print("-------------------------------------------")

# --- Main Execution ---
if __name__ == "__main__":
    # --- Configuration ---
    SCALE_PORT = 'COM4' # IMPORTANT: Change this to your scale's COM port
    SCALE_BAUD = 9600
    FORMATTED_LOG_FILENAME = 'formatted_weighing_log.csv'

    all_logged_weights = []
    controller = MettlerToledoController(port=SCALE_PORT, baudrate=SCALE_BAUD)

    print_help()

    try:
        while True:
            user_input = input("\nEnter command: ").strip()
            if not user_input:
                continue

            parts = user_input.split(maxsplit=1)
            command = parts[0].lower()

            if command == 'exit':
                print("Exiting program...")
                break
            elif command == 'help':
                print_help()
            elif command == 'connect':
                controller.connect()
            elif command == 'disconnect':
                controller.disconnect()
            elif command == 'reset':
                controller.power_on_or_reset()
            elif command == 'open':
                controller.open_doors()
            elif command == 'close':
                controller.close_doors()
            elif command == 'zero':
                controller.zero()
            elif command == 'stable':
                weight, unit = controller.get_stable_weight()
                if weight is not None:
                    print(f"Result: {weight:.5f} {unit}")
            elif command == 'now':
                weight, unit = controller.get_immediate_weight()
                if weight is not None:
                    print(f"Immediate Weight: {weight:.5f} {unit}")
                else:
                    print("Could not get an immediate weight reading.")
            elif command == 'log':
                print("Getting stable weight to log...")
                weight, unit = controller.get_stable_weight()
                if weight is not None:
                    formatted_weight = f"{weight:.5f} {unit}"
                    all_logged_weights.append(formatted_weight)
                    print(f"Logged reading #{len(all_logged_weights)}: {formatted_weight}")
                else:
                    print("Logging failed: Could not get a stable weight.")
            elif command == 'show':
                if not all_logged_weights:
                    print("No weights have been logged yet.")
                else:
                    print(f"\n--- Logged Weights ({len(all_logged_weights)}) ---")
                    for i, w in enumerate(all_logged_weights):
                        print(f"  {i+1}: {w}")
                    print("-------------------------")
            elif command == 'save':
                write_formatted_csv(FORMATTED_LOG_FILENAME, all_logged_weights)
            elif command == 'send':
                if len(parts) > 1:
                    raw_command = parts[1]
                    print(f"> Sending raw command: '{raw_command}'")
                    response = controller._send_command(raw_command)
                    print(f"< Response: {response}")
                else:
                    print("Usage: send <raw_command_to_scale>")
                    print("Example: send I4")
            else:
                print(f"Unknown command: '{command}'. Type 'help' for a list of commands.")

    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
    finally:
        # Ensure data is saved and connection is closed on exit
        if all_logged_weights:
            write_formatted_csv(FORMATTED_LOG_FILENAME, all_logged_weights)
        controller.disconnect()
        print("Program finished.")
