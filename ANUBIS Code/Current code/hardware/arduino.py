import serial
import time

class ArduinoController:
    """Handles all communication and logic for the Arduino door sensors."""
    def __init__(self, port, baudrate, timeout=1):
        self.connection = None
        try:
            self.connection = serial.Serial(port, baudrate, timeout=timeout)
            print(f"Successfully connected to Arduino on {port}")
            time.sleep(2)
        except serial.SerialException as e:
            print(f"Error: Could not connect to Arduino. {e}")

    def _get_statuses(self):
        """
        Requests, reads, and parses a single line from the Arduino.
        """
        if not self.connection or not self.connection.is_open:
            return None
        try:
            self.connection.reset_input_buffer()
            # Send the request ping
            self.connection.write(b'?')
            
            # Readline will wait until a newline is received or timeout expires
            raw_line = self.connection.readline().decode('utf-8').strip()
            
            if not raw_line:
                return None
            print(f"DEBUG: Arduino raw data: '{raw_line}'")
            
            # More robust parsing to handle potential whitespace (e.g., "pin5: Open")
            statuses = {}
            for part in raw_line.split(','):
                key_value_pair = part.split(':')
                if len(key_value_pair) == 2:
                    key = key_value_pair[0].strip()
                    value = key_value_pair[1].strip()
                    statuses[key] = value
            return statuses

        except Exception as e:
            print(f"Error processing Arduino message: {e}")
            return None

    def are_doors_open(self):
        """Checks if both door sensors (pins 5 & 7) report 'Open'.""" 
        statuses = self._get_statuses()
        if statuses:
            return statuses.get('pin5') == 'Open' and statuses.get('pin7') == 'Open'
        return False

    def are_doors_closed(self):
        """Checks if both door sensors (pins 5 & 7) report 'Closed'."""
        statuses = self._get_statuses()
        if statuses:
            return statuses.get('pin5') == 'Closed' and statuses.get('pin7') == 'Closed'
        return False

    def close(self):
        """Closes the serial connection gracefully."""
        if self.connection and self.connection.is_open:
            self.connection.close()
            print("Arduino connection closed.")
