import serial
import time
from tkinter import messagebox

class MettlerToledoController:
    """A class to connect to and control a Mettler Toledo scale."""
    def __init__(self, port, baudrate=9600, timeout=5, log_callback=None, arduino_controller=None, app_instance=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None
        self.log = log_callback if log_callback else print
        self.arduino = arduino_controller
        self.app = app_instance
        self.consecutive_weight_failures = 0

    def connect(self):
        try: 
            self.connection = serial.Serial(
                port=self.port, baudrate=self.baudrate, timeout=self.timeout,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS
            )
            time.sleep(0.1)
            if self.connection.is_open:
                self.log(f"-> Successfully connected to scale on {self.port}.")
                return True
            return False
        except serial.SerialException as e:
            self.log(f"Error connecting to scale: {e}")
            return False

    def disconnect(self):
        if self.connection and self.connection.is_open:
            self.connection.close()
            self.log("-> Disconnected from scale.")

    def _send_command(self, command):
        if not self.connection or not self.connection.is_open: return None
        try:
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()
            full_command = (command + "\r\n").encode('ascii')
            self.connection.write(full_command)
            time.sleep(0.3)
            lines = self.connection.readlines()
            response_lines = [line.decode('ascii').strip() for line in lines if line]
            if not response_lines:
                return ""
            if len(response_lines) == 1:
                return response_lines[0]
            # When app is used, it historically expected the last line. Tests expected joined lines.
            return response_lines[-1] if self.app else " | ".join(response_lines)
        except Exception as e:
            self.log(f"Scale command error: {e}")
            return None
        
    def _send_command_no_response(self, command):
        if not self.connection or not self.connection.is_open:
           self.log("Cannot send command: Scale is not connected.")
           return False

        try:
           self.connection.reset_input_buffer()
           self.connection.reset_output_buffer()
           full_command = (command + "\r\n").encode('ascii')
           self.connection.write(full_command)
           self.log(f"Sent command '{command}' with no response expected.")
           return True
        except Exception as e:
           self.log(f"Error sending command '{command}': {e}")
           return False

    def power_on_or_reset(self):
        self.log("   -> Sending '@' command to wake scale...")
        self._send_command("@")
        time.sleep(1.5)
        self.log("   -> Scale should be active.")

    def get_stable_weight(self, max_retries=7):
        self.log("   -> Requesting stable weight...")
        for attempt in range(max_retries):
            response = self._send_command("S")
            if response and response.startswith("S S"):
                try:
                    parts = response.split()
                    weight, unit = float(parts[2]), parts[3]
                    self.log(f"   <- Stable weight received: {weight} {unit}")
                    return weight, unit
                except (IndexError, ValueError): pass
            self.log(f"     - Attempt {attempt + 1}: Unstable. Retrying...")
            time.sleep(0.5)
        self.log("   <- Failed to get a stable weight.")
        return None, None

    def get_immediate_weight(self):
        """Requests an immediate weight reading, regardless of stability."""
        response = self._send_command("SI")
        if response is None:
            return None, None
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

    def stable_weight_error(self, user_name):
        self.log("!!! ERROR: scale failure.")
        error_msg = "Scale is unstable. User support is required to continue."
        if self.app:
            self.app.root.after(0, self.app.send_gchat_notification, error_msg, user_name)
        should_retry = (self.app.safe_askretrycancel if self.app else messagebox.askretrycancel)(
            title="Scale Unstable Error",
            message=("The scale could not get a stable weight after multiple attempts.\n\n"
                    "- Click 'Retry' to clear the error and attempt another reading.\n"
                    "- Click 'Cancel' to stop the entire process.")
        )
        if should_retry:
            self.log("-> User chose to RETRY.")
        else:
            self.log("!!! User chose to CANCEL the process due to unstable scale.")
        return should_retry

    def zero(self):
        self.log("   -> Zeroing scale...")
        self._send_command("Z")
        time.sleep(1)

    def tare(self, max_retries=7):
        self.log("   -> Taring scale...")
        for attempt in range(max_retries):
            response = self._send_command("T")
            if response and response.startswith("T S"):
                try:
                    parts = response.split()
                    weight = float(parts[2])
                    unit = parts[3] if len(parts) > 3 else 'g'
                    self.log(f"   <- Scale tared. Tare weight: {weight} {unit}")
                    return True
                except (IndexError, ValueError): pass
            self.log(f"     - Attempt {attempt + 1}: Unstable or executing. Retrying tare...")
            time.sleep(1)
        self.log("   <- Failed to tare scale.")
        return False

    def open_doors(self, app_instance=None, user_name=None):
        if app_instance:
            self.app = app_instance
        self.log("> Attempting to open doors (WS 5)...")
        self._send_command_no_response("WS 5")

        if self.arduino:
          self.log("--> Checking Arduino sensors for 'Open' confirmation...")
          start_time = time.time()
          while time.time() - start_time < 5:
            if self.arduino.are_doors_open():
                self.log("Success: Arduino confirms doors are OPEN.")
                return True
            time.sleep(0.02)
        self.log("Warning: Failed to confirm doors are open. Retrying automatically...")
        self._send_command("WS 5")
        time.sleep(1.5)

        response = self._send_command("WS")
        if response == "WS A 5":
            self.log("Success: Doors opened on automatic retry.")
            return True
        
        self.log("ERROR: Automatic retry failed. Asking user for intervention.")
        while True:
            if self.app and user_name:
                self.app.root.after(0, self.app.send_gchat_notification, "(open) Door obstruction detected, User support is required to continue.", user_name)
            
            should_retry = (self.app.safe_askretrycancel if self.app else messagebox.askretrycancel)(
                title="Scale Open Door Error",
                message="The scale doors failed to open after an automatic retry. Please check for obstructions.\n\n- Click 'Retry' to try opening them again.\n- Click 'Cancel' to stop the entire process.")
            if not should_retry:
                self.log("!!! User chose to CANCEL the process due to door failure.")
                return False
            self.log("-> User chose to RETRY. Trying to open doors again...")
            self._send_command_no_response("WS 5")
            if self.arduino:
              self.log("--> [User Retry] Checking Arduino sensors (5s timeout)...")
              start_time = time.time()
              while time.time() - start_time < 5:
                if self.arduino.are_doors_open():
                    self.log("Success: Arduino confirms doors are OPEN after user retry.")
                    return True
                time.sleep(0.02)
            response = self._send_command("WS")
            time.sleep(1.5)
            if response == "WS A 5":
                self.log("Success: Doors opened after user retry (confirmed by scale).")
                return True
            self.log("ERROR: Manual retry failed. Please check for obstructions again.")

    def close_doors(self, app_instance=None, user_name=None):
        if app_instance:
            self.app = app_instance
        self.log("> Attempting to close doors (WS 0)...")
        self._send_command_no_response("WS 0")

        if self.arduino:
           self.log("--> Checking Arduino sensors for 'Closed' confirmation...")
           start_time = time.time()
           while time.time() - start_time < 5:
            if self.arduino.are_doors_closed():
                self.log("Success: Arduino confirms doors are CLOSED.")
                return True
            time.sleep(0.02)

        self.log("Warning: Failed to confirm doors are closed. Retrying automatically...")
        self._send_command("WS 0")
        time.sleep(1.5)
        response = self._send_command("WS")
        if response == "WS A 0":
            self.log("Success: Doors closed on automatic retry.")
            return True
        
        self.log("ERROR: Automatic retry failed. Asking user for intervention.")
        while True:
            if self.app and user_name:
                self.app.root.after(0, self.app.send_gchat_notification, "(Closed) Door obstruction detected, User support is required to continue.", user_name)
            
            should_retry = (self.app.safe_askretrycancel if self.app else messagebox.askretrycancel)(
                title="Scale Closed Door Error",
                message="The scale doors failed to close after an automatic retry. Please check for obstructions.\n\n- Click 'Retry' to try closing them again.\n- Click 'Cancel' to stop the entire process.")
            if not should_retry:
                self.log("!!! User chose to CANCEL the process due to door failure.")
                return False
            self.log("-> User chose to RETRY. Trying to close doors again...")
            self._send_command_no_response("WS 0")
            if self.arduino:
              self.log("--> [User Retry] Checking Arduino sensors (5s timeout)...")
              start_time = time.time()
              while time.time() - start_time < 5:
                if self.arduino.are_doors_closed():
                    self.log("Success: Arduino confirms doors are CLOSED after user retry.")
                    return True
                time.sleep(0.02)
            response = self._send_command("WS")
            time.sleep(1.5)
            if response == "WS A 0":
                self.log("Success: Doors closed after user retry.")
                return True
            self.log("ERROR: Manual retry failed. Please check for obstructions again.")

    def scale_adjustment_check(self, app_instance=None, user_name=None, timeout=120):
        if app_instance:
            self.app = app_instance
        self.log("Checking scale adjustment status...")
        response = self._send_command("C0")
        self.log(f"-> Scale response for 'C0' command: '{response}'")

        if response == 'C0 A 2 0 ""':
            self.log("Warning: Scale adjustment is required. Starting automatic adjustment...")
            
            while True:
                self.connection.reset_input_buffer()
                self.connection.write("C3\r\n".encode('ascii'))
                
                first_resp = self.connection.readline().decode('ascii').strip()
                if first_resp != "C3 B":
                    self.log(f"ERROR: Failed to start scale adjustment. Scale said: {first_resp}")
                    return False
                
                if self.app and user_name:
                    self.app.root.after(0, self.app.send_gchat_notification, "Scale adjustment in progress...", user_name)
                self.log("Adjustment in progress... Waiting for completion signal from scale...")
                
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if self.connection.in_waiting > 0:
                        final_resp = self.connection.readline().decode('ascii').strip()
                        if final_resp == "C3 A":
                            self.log("Success: Scale adjustment completed successfully.")
                            if self.app and user_name:
                                self.app.root.after(0, self.app.send_gchat_notification, "Scale adjustment sucessful, zeroing scale then resuming process.", user_name)
                            self.log("Zeroing scale")
                            self._send_command("Z")
                            time.sleep(1)
                            return True
                        elif final_resp == "C3 I":
                            self.log("ERROR: Scale aborted the adjustment (e.g., stability not attained).")
                            break
                    time.sleep(0.5)

                self.log("ERROR: Scale adjustment failed or timed out. Asking user for intervention.")
                if self.app and user_name:
                    self.app.root.after(0, self.app.send_gchat_notification, "Scale adjustment failed, user support is required.", user_name)

                should_retry = (self.app.safe_askretrycancel if self.app else messagebox.askretrycancel)(
                    title="Scale Adjustment Error",
                    message="The scale failed to adjust automatically after a timeout. This could be due to instability or an internal error.\n\n- Click 'Retry' to try the adjustment again.\n- Click 'Cancel' to stop the entire process."
                )

                if not should_retry:
                    self.log("!!! User chose to CANCEL the process due to adjustment failure.")
                    return False
                
                self.log("-> User chose to RETRY. Trying adjustment again...")
        
        elif 'C0 A 1 0 ""' in response:
            self.log("Success: Scale adjustment is not required.")
            return True
        else:
            self.log(f"ERROR: Could not determine scale adjustment status. Response: {response}")
            return False
