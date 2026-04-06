import socket
import re
import time

class Meca500Resetter:
    """
    A class to connect to, reset, and home a Meca500 robot.
    Encapsulates the entire reset and home sequence.
    """
    def __init__(self, ip='192.168.0.100', port=10000):
        """
        Initializes the Meca500Resetter with the robot's address.
        ip (str): The IP address of the Meca500 robot.
        port (int): The control port of the robot (usually 10000).
        """
        self.robot_ip = ip
        self.control_port = port

    def _send_command(self, sock, command_str):
        """
        (Internal helper method)
        Sends a command to the robot, waits for, and returns the response.
        """
        print(f"-> Sending: {command_str}")
        sock.sendall((command_str + '\0').encode('ascii')) # sends command to the arm api
        response = sock.recv(1024).decode('ascii').strip() # waits and processes the reply from the arm api
        print(f"<- Received: {response}")
        return response

    def reset_and_home(self):
        """
        Connects to the Meca500, clears any error state, and moves it
        through a predefined sequence to the home position.

        Returns:
            bool: True if the sequence completes successfully, False otherwise.
        """
        print("--- Initiating Meca500 Arm Error Reset & Home Sequence ---")
        sequence_timeout = 60  # Total time for the entire sequence

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(sequence_timeout)
                sock.connect((self.robot_ip, self.control_port))
                print(f"Successfully connected to {self.robot_ip}.")

                # 1. Synchronize by clearing the robot's welcome message
                initial_msg = sock.recv(1024).decode('ascii').strip()
                print(f"Robot's welcome message: {initial_msg}")
                
                # 2. Perform Recovery and Activation
                print("\n--- Sending Recovery & Activation Commands ---")
                self._send_command(sock, "ActivateRobot")
                self._send_command(sock, "ResetError")
                self._send_command(sock, "ResumeMotion")
                print("Pausing for 1 second to ensure robot is ready...")
                time.sleep(1)

                # 3. Execute Motion Sequence
                print("\n--- Starting Motion Sequence ---")
                response = self._send_command(sock, "GetJoints")
                match = re.search(r'\[(-?[\d\.]+),(-?[\d\.]+),(-?[\d\.]+),(-?[\d\.]+),(-?[\d\.]+),(-?[\d\.]+)\]', response) # gets joint position of robot
                if not match:
                    print("CRITICAL ERROR: Could not parse joint angles. Aborting.")
                    return False

                current_joints = [float(j) for j in match.groups()]
                print(f"Current joints captured: {[f'{j:.2f}' for j in current_joints]}")

                # Define poses and send commands
                cancel_pose_1 = [current_joints[0], -25.96, 64.97, -0.83, -40.07, -2.39]
                cancel_pose_2 = [0, -25.96, 64.97, -0.83, -40.07, -2.39]
                home_pose = [0, 0, 0, 0, 0, 0]

                self._send_command(sock, f"MoveJoints({','.join([f'{j:.2f}' for j in cancel_pose_1])})")
                self._send_command(sock, f"MoveJoints({','.join([f'{j:.2f}' for j in cancel_pose_2])})")
                self._send_command(sock, f"MoveJoints({','.join([f'{j:.2f}' for j in home_pose])})")

                # 4. Wait for Motion to Complete by Polling
                print("\nWaiting for motion to complete by polling status...")
                polling_timeout = 45
                start_time = time.time()
                while time.time() - start_time < polling_timeout:
                    status_response = self._send_command(sock, "GetStatusRobot")
                    status_match = re.search(r'\[(\d),(\d),(\d),(\d),(\d),(\d),(\d)\]', status_response)
                    if status_match and status_match.groups()[6] == '1':
                        print("Motion queue is empty. Sequence complete.")
                        print("\n Robot reset sequence finished successfully.")
                        return True
                    time.sleep(0.5)
                else:
                    print("Timed out waiting for motion to complete.")
                    return False

        except socket.timeout:
            print("ERROR: Connection to robot timed out.")
            return False
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return False
