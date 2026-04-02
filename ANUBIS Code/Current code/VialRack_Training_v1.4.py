import mecademicpy.robot as mdr
import time
import tkinter as tk
from tkinter import simpledialog, scrolledtext, messagebox, ttk, filedialog
import sys
import threading
import queue
import csv
import os
from datetime import datetime
import re
import json
import glob

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.utils import ProcessCancelledError, coordinate_to_index, index_to_coordinate
class RobotTrainingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mecademic Robot Training")
        self.root.geometry("600x550")
        self.root.eval('tk::PlaceWindow . center')
        self.root.configure(bg='#f0f0f0')

        self.nest_configs = [None, None, None]
        self.log_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.robot = None
        self.is_paused = False

        self.common_params = {
            "ROBOT_IP": "192.168.0.100",
            "home_position_joints": [-90, 0, 0, 0, 0, 0],
        }

        self.create_widgets()
        self.process_log_queue()

    def create_widgets(self):
        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        setup_frame = tk.LabelFrame(main_frame, text="Training Setup", font=("Arial", 12, "bold"), bg='#f0f0f0', padx=10, pady=10)
        setup_frame.pack(fill=tk.X, pady=10)

        # Add Start/End Coordinate Entries
        coord_frame = tk.Frame(setup_frame, bg='#f0f0f0')
        coord_frame.pack(fill=tk.X, pady=5, padx=5)

        tk.Label(coord_frame, text="Start Coordinate:", bg='#f0f0f0').pack(side=tk.LEFT)
        self.start_coord_entry = tk.Entry(coord_frame, width=10)
        self.start_coord_entry.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(coord_frame, text="End Coordinate:", bg='#f0f0f0').pack(side=tk.LEFT)
        self.end_coord_entry = tk.Entry(coord_frame, width=10)
        self.end_coord_entry.pack(side=tk.LEFT)

        self.file_labels = []
        for i in range(3):
            nest_frame = tk.Frame(setup_frame, bg='#f0f0f0')
            nest_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(nest_frame, text=f"Nest {i+1}:", bg='#f0f0f0', width=8).pack(side=tk.LEFT)
            
            select_button = tk.Button(nest_frame, text="Select File...", command=lambda idx=i: self.select_file(idx))
            select_button.pack(side=tk.LEFT, padx=5)
            
            file_label = tk.Label(nest_frame, text="No file selected", bg='#e0e0e0', anchor='w', relief='sunken', padx=5)
            file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.file_labels.append(file_label)

        self.start_button = tk.Button(main_frame, text="Start Training", font=("Arial", 12, "bold"), command=self.start_training, bg='#4CAF50', fg='white')
        self.start_button.pack(pady=10, fill=tk.X)
        
        self.pause_resume_button = tk.Button(main_frame, text="Pause", font=("Arial", 12, "bold"), command=self.toggle_pause_resume, bg='#007BFF', fg='white', state=tk.DISABLED)
        self.pause_resume_button.pack(pady=5, fill=tk.X)
        
        self.stop_button = tk.Button(main_frame, text="Stop Training", font=("Arial", 12, "bold"), command=self.stop_training, bg='#F44336', fg='white', state=tk.DISABLED)
        self.stop_button.pack(pady=5, fill=tk.X)

        log_frame = tk.Frame(main_frame, bg='#f0f0f0')
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        tk.Label(log_frame, text="Log:", font=("Arial", 12), bg='#f0f0f0').pack(anchor='w')
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', wrap=tk.WORD, font=("Courier New", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)

    def select_file(self, index):
        filepath = filedialog.askopenfilename(
            title=f"Select Configuration for Nest {index+1}",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
        )
        if filepath:
            try:
                with open(filepath, 'r') as f:
                    config = json.load(f)
                self.nest_configs[index] = config
                self.file_labels[index].config(text=os.path.basename(filepath))
                self.log(f"Loaded config for Nest {index+1}: {os.path.basename(filepath)}")
            except Exception as e:
                messagebox.showerror("File Error", f"Failed to load or parse file:\n{e}")
                self.log(f"Error loading file for Nest {index+1}: {e}")

    def log(self, message):
        self.log_queue.put(message)

    def process_log_queue(self):
        try:
            while not self.log_queue.empty():
                message = self.log_queue.get_nowait()
                self.log_text.config(state='normal'); self.log_text.insert(tk.END, message + '\n'); self.log_text.config(state='disabled'); self.log_text.see(tk.END)
        finally:
            self.root.after(100, self.process_log_queue)

    def start_training(self):
        start_coord_str = self.start_coord_entry.get().strip()
        end_coord_str = self.end_coord_entry.get().strip()

        if not start_coord_str or not end_coord_str:
            messagebox.showerror("Input Error", "Please enter both a Start and End Coordinate.")
            return

        tasks = []
        for i, config in enumerate(self.nest_configs):
            if config:
                task_params = {**config, **self.common_params, "name": f"Nest {i+1}"}
                tasks.append(task_params)

        if not tasks:
            messagebox.showwarning("No Tasks", "Please select at least one configuration file.")
            return

        self.cancel_event.clear()
        self.start_button.config(state=tk.DISABLED)
        self.start_coord_entry.config(state=tk.DISABLED)
        self.end_coord_entry.config(state=tk.DISABLED)
        self.pause_resume_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL)
        
        self.robot_thread = threading.Thread(target=self.robot_task, args=(tasks, start_coord_str, end_coord_str), daemon=True)
        self.robot_thread.start()

    def stop_training(self):
        self.log("!!! STOP REQUESTED BY USER !!!")
        if self.is_paused:
            self.toggle_pause_resume() # Resume motion before cancelling
        self.cancel_event.set()
        self.stop_button.config(state=tk.DISABLED, text="Stopping...")

    def toggle_pause_resume(self):
        if not self.robot or not self.robot.IsConnected():
            return
        if self.is_paused:
            self.robot.ResumeMotion()
            self.log("-> Motion Resumed.")
            self.pause_resume_button.config(text="Pause")
            self.is_paused = False
        else:
            self.robot.PauseMotion()
            self.log("--- Motion Paused ---")
            self.pause_resume_button.config(text="Resume")
            self.is_paused = True

    def task_completed(self):
        self.start_button.config(state=tk.NORMAL)
        self.start_coord_entry.config(state=tk.NORMAL)
        self.end_coord_entry.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED, text="Stop Training")
        self.pause_resume_button.config(state=tk.DISABLED, text="Pause")
        self.is_paused = False

    def robot_task(self, tasks, start_coord_str, end_coord_str):
        self.robot = mdr.Robot()
        
        def check_for_events():
            if self.cancel_event.is_set(): raise ProcessCancelledError("Process cancelled by user.")

        try:
            self.log(f"Connecting..."); self.robot.Connect(address=self.common_params["ROBOT_IP"]); check_for_events()
            self.robot.ActivateRobot(); check_for_events()
            self.robot.Home(); check_for_events()
            self.log("-> Robot Homed and Activated.")
            
            self.log("-> Moving to home position before starting.")
            self.robot.MoveJoints(*self.common_params['home_position_joints']); self.robot.WaitIdle(); check_for_events()

            self.robot.SetJointVel(50); self.robot.SetJointAcc(50)
            
            for nest_params in tasks:
                self.log(f"\n********** STARTING TRAINING FOR {nest_params['name']} **********"); check_for_events()
                
                GRIPPER_OPEN = nest_params.get('gripper_open_dist', 2.7)
                GRIPPER_CLOSE = nest_params.get('gripper_close_dist', 0)
                LIFT_UP_MM = nest_params.get('lift_up_mm', 50.0)
                INCREMENT_1X = nest_params.get('increment_1x_mm', -9.0)
                INCREMENT_1Y = nest_params.get('increment_1y_mm', 9.0)
                INCREMENT_2X = nest_params.get('increment_2x_mm', -9.0)
                INCREMENT_2Y = nest_params.get('increment_2y_mm', 9.0)
                INCREMENT_3X = nest_params.get('increment_3x_mm', -9.0)
                INCREMENT_3Y = nest_params.get('increment_3y_mm', 9.0)
                RESET_INTERVAL = nest_params.get('row_reset_interval', 8)
                MAX_WELLS = nest_params.get('max_wells', 96)
                
                base_pose_key = f"base_pose_{nest_params['name'].lower().replace(' ', '_')}"
                base_pose = nest_params.get(base_pose_key)
                if not base_pose:
                    self.log(f"ERROR: Config for {nest_params['name']} is missing '{base_pose_key}'. Skipping.")
                    continue

                start_index = coordinate_to_index(start_coord_str, MAX_WELLS, RESET_INTERVAL)
                end_index = coordinate_to_index(end_coord_str, MAX_WELLS, RESET_INTERVAL)

                if start_index == -1 or end_index == -1 or end_index < start_index:
                    self.log(f"ERROR: Invalid coordinates '{start_coord_str}' or '{end_coord_str}' for {nest_params['name']}. Skipping.")
                    continue

                for i in range(start_index, end_index + 1):
                    self.log(f"--- Testing Vial {index_to_coordinate(i, MAX_WELLS, RESET_INTERVAL)} ({nest_params['name']}) ---"); check_for_events()
                    
                    group_number, step_in_group = divmod(i, RESET_INTERVAL)
                    current_target_pose = list(base_pose)
                    
                    # Apply offsets based on nest
                    if nest_params['name'] == 'Nest 1':
                        x_offset = step_in_group * INCREMENT_1X
                        y_offset = group_number * INCREMENT_1Y
                        current_target_pose[0] += x_offset
                        current_target_pose[1] -= y_offset 
                    elif nest_params['name'] == 'Nest 2':
                        y_offset = step_in_group * INCREMENT_2Y
                        x_offset = group_number * INCREMENT_2X
                        current_target_pose[1] += y_offset
                        current_target_pose[0] += x_offset
                    elif nest_params['name'] == 'Nest 3':
                        x_offset = step_in_group * INCREMENT_3X
                        y_offset = group_number * INCREMENT_3Y
                        current_target_pose[0] -= x_offset 
                        current_target_pose[1] += y_offset 

                    approach_pose = list(current_target_pose); approach_pose[2] += LIFT_UP_MM
                    
                    self.robot.MovePose(*approach_pose); self.robot.WaitIdle(); check_for_events()
                    self.robot.MoveLin(*current_target_pose); self.robot.WaitIdle(); check_for_events()
                    self.robot.MoveGripper(GRIPPER_CLOSE); self.robot.WaitIdle(); time.sleep(0.5); check_for_events()
                    
                    self.robot.MoveLin(*approach_pose); self.robot.WaitIdle(); check_for_events()
                    
                    self.robot.MoveLin(*current_target_pose); self.robot.WaitIdle(); check_for_events()
                    self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); time.sleep(0.5); check_for_events()
                    
                    self.robot.MoveLin(*approach_pose); self.robot.WaitIdle(); check_for_events()

            self.log("***** All training tasks are complete. *****")
            self.robot.MoveJoints(*self.common_params['home_position_joints']); self.robot.WaitIdle()
        
        except ProcessCancelledError as e:
            self.log(str(e)); self.log("Aborting process...")
            if self.robot and self.robot.IsConnected():
                self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle()
                self.robot.MoveJoints(*self.common_params["home_position_joints"]); self.robot.WaitIdle()
        except Exception as e:
            self.log(f"\n!!!!!!!! AN ERROR OCCURRED !!!!!!!!\n{e}\n")
        
        finally:
            if self.robot and self.robot.IsConnected():
                self.log("Disconnecting robot..."); self.robot.DeactivateRobot(); self.robot.Disconnect(); self.log("-> Disconnected.")
            self.root.after(0, self.task_completed)

if __name__ == "__main__":
    root = tk.Tk()
    app = RobotTrainingApp(root)
    root.mainloop()
