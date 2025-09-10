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

class MettlerToledoController:
    """
    A class to connect to and control a Mettler Toledo scale.
    """

    def __init__(self, port, baudrate=9600, timeout=5):
        """Initializes the scale controller object."""
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None

    def connect(self):
        """Establishes the serial connection to the scale."""
        try:
            self.connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )
            time.sleep(0.5)
            if self.connection.is_open:
                print(f"Successfully connected to scale on {self.port} at {self.baudrate} baud.")
                return True
            print("Failed to open the serial connection.")
            return False
        except serial.SerialException as e:
            print(f"Error connecting to scale: {e}")
            return False

    def disconnect(self):
        """Closes the serial connection."""
        if self.connection and self.connection.is_open:
            self.connection.close()
            print("\nDisconnected from scale.")

    def _send_command(self, command):
        """A robust internal function to send a command and get a response."""
        if not self.connection or not self.connection.is_open:
            print("Error: Not connected to the scale.")
            return None
        try:
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()
            full_command = (command + "\r\n").encode('ascii')
            self.connection.write(full_command)
            time.sleep(0.3)
            lines = self.connection.readlines()
            if not lines:
                # Some commands don't have a response, this is normal.
                return ""
            # Return all non-empty lines from the response, joined together
            response_lines = [line.decode('ascii').strip() for line in lines if line]
            return " | ".join(response_lines) if response_lines else ""
        except Exception as e:
            print(f"An error occurred while sending command '{command}': {e}")
            return None

    def power_on_or_reset(self):
        """Sends the '@' reset command to wake the scale from standby."""
        print("Sending '@' reset command to wake scale...")
        response = self._send_command("@")
        if response is not None:
            time.sleep(1.5) # Give scale extra time to initialize
            print("Scale should be active.")

    def get_stable_weight(self, max_retries=10):
        """
        Requests a stable weight reading from the scale, retrying if unstable.
        """
        print("> Requesting stable weight...")
        for attempt in range(max_retries):
            response = self._send_command("S")
            if response and response.startswith("S S"):
                try:
                    parts = response.split()
                    weight = float(parts[2])
                    unit = parts[3]
                    print(f"< Stable weight received: {weight} {unit}")
                    return weight, unit
                except (IndexError, ValueError) as e:
                    print(f"  - Error parsing stable weight response: {e}")
                    pass # Ignore parsing errors and retry
            elif response is None:
                # Stop retrying if the connection failed
                return None, None
            
            # If not stable, wait a moment before trying again
            print(f"  - Attempt {attempt + 1}: Weight is not stable. Retrying...")
            time.sleep(0.5)
        
        print("< Failed to get a stable weight after multiple attempts.")
        return None, None
        
    def get_immediate_weight(self):
        """Requests an immediate weight reading, regardless of stability."""
        response = self._send_command("SI")
        if response is None:
            return None, None
        # Handles both stable 'S S' and unstable 'S I' responses
        if response and response.startswith("S"):
            try:
                parts = response.split()
                if len(parts) >= 3:
                    weight = float(parts[2])
                    unit = parts[3] if len(parts) > 3 else 'g'
                    return weight, unit
            except (IndexError, ValueError):
                return None, None
        return None, None

    def zero(self):
        """Sends the 'Zero' command to the scale."""
        print("> Zeroing scale...")
        response = self._send_command("Z")
        if response is not None:
            time.sleep(1) # Wait for zeroing to complete
            print("Scale zeroed.")

    def open_doors(self):
        """Sends the command to open the top and right doors."""
        print(f"> Opening doors (WS 6)...{datetime.now().time()}")
        response = self._send_command("WS 6")
        if response is not None:
            #time.sleep(2) # Allow time for mechanical action
            print(f"Doors opened.{datetime.now().time()}")

    def close_doors(self):
        """Sends the command to close all doors."""
        print("> Closing doors (WS 0)...")
        response = self._send_command("WS 0")
        if response is not None:
            time.sleep(2) # Allow time for mechanical action
            print("Doors closed.")

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
