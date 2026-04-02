import tkinter as tk
import tkinter
import customtkinter
from tkinter import simpledialog, scrolledtext, messagebox, ttk, font
import time
import os
import csv
import queue
import threading
import datetime
from datetime import datetime
import json
import glob
import webbrowser
import requests
import ctypes
from PIL import ImageTk, Image
import mecademicpy.robot as mdr

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import APP_CONFIG
from core.utils import ProcessCancelledError, coordinate_to_index, index_to_coordinate
from hardware.arduino import ArduinoController
from hardware.scale import MettlerToledoController
from hardware.robot import Meca500Resetter
from hardware.scanner import BarcodeScannerListener

def show_splash(main_window, image_path, duration_ms):
    """
    Displays a centered splash screen. Shows an error popup if the image is not found.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1) # handles the scaling of the splash screen
    except Exception:
        pass 

    main_window.withdraw()
    splash_root = tk.Toplevel(main_window)
    splash_root.overrideredirect(True)

    try:
        # --- Attempt to load the image ---
        pil_image = Image.open(image_path)
        splash_image = ImageTk.PhotoImage(pil_image)
        tk.Label(splash_root, image=splash_image, bd=0).pack()
        splash_root.image = splash_image # Keep a reference
        img_width, img_height = pil_image.width, pil_image.height
   
    except Exception as e:
        # Catch other potential errors (e.g., corrupted image)
        messagebox.showerror("Splash Screen Error", f"An unexpected error occurred while loading the image:\n{e}")
        main_window.destroy() # Exit if splash fails
        return

    # --- Center the splash screen ---

    try:
        # This works reliably on Windows
        screen_width = ctypes.windll.user32.GetSystemMetrics(0)
        screen_height = ctypes.windll.user32.GetSystemMetrics(1)
    except AttributeError:
        # Fallback for non-Windows systems
        screen_width = main_window.winfo_screenwidth()
        screen_height = main_window.winfo_screenheight()

    x_pos = (screen_width // 2) - (img_width // 2)
    y_pos = (screen_height // 2) - (img_height // 2)
    splash_root.geometry(f'{img_width}x{img_height}+{x_pos}+{y_pos}')

    def show_main_window():
        splash_root.destroy()
        main_window.deiconify()

    main_window.after(duration_ms, show_main_window)

class RobotUiApp:
    
    def __init__(self, root):
        # ... your other initializations ...
        self.cycle_count = 0  # for checking if the scale needs an adjustment

    def __init__(self, root):
        self.root = root # the main window of the gui
        self.root.title("Anubis Control Interface")
        self.root.geometry("1000x700")
        

        self.nest_widgets = []
        self.log_queue = queue.Queue()
        self.barcode_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.scanner_listener = None
        self.scanner_thread = None
        self.robot = None
        self.gchat_webhook_url = APP_CONFIG["notifications"]["gchat_webhook_url"]
        
        self.rack_configs = self.load_rack_configs()
        self.nest_locations = ["Nest 1", "Nest 2", "Nest 3"]

        self.common_params = {
            "ROBOT_IP": APP_CONFIG["hardware"]["robot_ip"],
            "SCALE_PORT": APP_CONFIG["hardware"]["scale_port"],
            "ARDUINO_PORT": APP_CONFIG["hardware"]["arduino_port"],
            "home_position_joints": [0, 0, 0, 0, 0, 0],
            "intermediate_pose_2": [89.363144, 85.359945, 226.828754, -85.065301, 46.75398, 88.841213],
            "intermediate_pose_3": [3.45444, 114.014649, 233.783148, -89.652968, 1.924481, 88.717395],
            "intermediate_pose_4": [-0.768729, 261.00615, 160, -90, -0.16875, 90],
            "intermediate_pose_nest3_safety": [-90,0,0,0,0,0],
            "scanner_pose": [256.324502, 75.744832, 205.200681, -87.478169, 73.592046, 88.744038],
            "LOG_FILE_PATH": APP_CONFIG["paths"]["log_files"],
            "CSV_FILE_PATH": APP_CONFIG["paths"]["csv_files"]
        }
        self.scanner_params = {"CSV_HEADER": ['Coordinate', 'Scanned Barcode','Vial Weight']}

        self.create_widgets()
        self.process_log_queue()
        if not self.rack_configs:
            self.log("No rack configuration files found. Please check the path and folder content.")
            messagebox.showerror("Config Error", "No rack configuration files were found. The application cannot start tasks without them.")

    def load_rack_configs(self):
        """Loads all .json configuration files from the specified directory."""
        configs_path = APP_CONFIG["paths"]["rack_library"]
        if not os.path.exists(configs_path):
            self.log(f"Warning: Configuration directory '{configs_path}' not found.")
            return {}
        
        config_files = glob.glob(os.path.join(configs_path, "*.json"))
        rack_options = {}
        for f_path in config_files:
            try:
                with open(f_path, 'r') as file:
                    config = json.load(file)
                    rack_name = config.get("rack_name")
                    if rack_name:
                        rack_options[rack_name] = config
                    else:
                        self.log(f"Warning: Config file {f_path} is missing 'rack_name'.")
            except (json.JSONDecodeError, KeyError) as e:
                self.log(f"Error loading config file {f_path}: {e}")
        return rack_options

    def create_widgets(self):
        # --- Configure the main grid layout ---
        self.root.grid_columnconfigure(0, weight=1) # Log column
        self.root.grid_columnconfigure(1, weight=1) # Controls column
        self.root.grid_rowconfigure(0, weight=1)

        # --- Left Frame for System Log ---
        left_frame = customtkinter.CTkFrame(self.root, corner_radius=10)
        left_frame.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")
        left_frame.grid_rowconfigure(1, weight=1) # Make the log text box expand
        left_frame.grid_columnconfigure(0, weight=1)
        
        log_label = customtkinter.CTkLabel(left_frame, text="System Log", font=customtkinter.CTkFont(size=16, weight="bold"))
        log_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        self.log_text = customtkinter.CTkTextbox(left_frame, wrap=tkinter.WORD, font=("Courier New", 13), corner_radius=8)
        self.log_text.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.log_text.configure(state="disabled")

        # --- Emergency Shutdown Button (Under the System Log) ---
        self.emergency_shutdown_button = customtkinter.CTkButton(
            left_frame,  # Parent is the left_frame
            text="EMERGENCY SHUTDOWN", command=self.emergency_shutdown, height=40, fg_color="#E53935", hover_color="#C62828", font=customtkinter.CTkFont(size=14, weight="bold"),text_color="black")
        self.emergency_shutdown_button.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        # --- Right Frame for Controls ---
        right_frame = customtkinter.CTkFrame(self.root, fg_color="transparent")
        right_frame.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=1)  
        right_frame.grid_columnconfigure(0, weight=1)

        # --- Create a scrollable frame for the nest setup area ---
        nest_scroll_frame = customtkinter.CTkScrollableFrame(right_frame, label_text=None, fg_color="transparent")
        nest_scroll_frame.grid(row=0, column=0, sticky="nsew")

        # --- Process Setup Frame (inside the scrollable frame) ---
        setup_frame = customtkinter.CTkFrame(nest_scroll_frame, corner_radius=10)
        setup_frame.pack(fill="x", expand=True, padx=0, pady=0)
        
        setup_label = customtkinter.CTkLabel(setup_frame, text="Process Setup", font=customtkinter.CTkFont(size=16, weight="bold"))
        setup_label.pack(anchor="w", padx=15, pady=(10, 5))
        
        user_frame = customtkinter.CTkFrame(setup_frame, fg_color="transparent")
        user_frame.pack(fill="x", padx=15, pady=(5, 10))
        customtkinter.CTkLabel(user_frame, text="Your Email:").pack(side="left")
        self.user_name_entry = customtkinter.CTkEntry(user_frame, placeholder_text="Enter email without @calicolabs.com")
        self.user_name_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))

        for i, nest_name in enumerate(self.nest_locations):
            nest_container = customtkinter.CTkFrame(setup_frame, border_width=1)
            nest_container.pack(fill="x", expand=True, padx=15, pady=5)
            
            widgets = {'name': nest_name}
            
            widgets['enabled_var'] = tkinter.BooleanVar()
            widgets['enable_check'] = customtkinter.CTkCheckBox(nest_container, text=nest_name, variable=widgets['enabled_var'], command=lambda idx=i: self.toggle_nest_inputs(idx))
            widgets['enable_check'].pack(anchor='w', padx=10, pady=10)

            options_frame = customtkinter.CTkFrame(nest_container, fg_color="transparent")
            widgets['options_frame'] = options_frame
            
            options_frame.columnconfigure(1, weight=1)

            # --- Create and grid all options widgets ---
            tk_label = customtkinter.CTkLabel(options_frame, text="Rack Type:")
            tk_label.grid(row=0, column=0, sticky='w', pady=4, padx=10)
            widgets['rack_type_combo'] = customtkinter.CTkComboBox(options_frame, values=list(self.rack_configs.keys()), command=lambda choice, idx=i: self.on_rack_type_change(idx))
            widgets['rack_type_combo'].grid(row=0, column=1, sticky='ew', padx=10, pady=4)
            widgets['rack_type_combo'].set("Select Rack...")

            tk_label = customtkinter.CTkLabel(options_frame, text="Is Rack Full?")
            tk_label.grid(row=1, column=0, sticky='w', pady=4, padx=10)
            widgets['rack_full_combo'] = customtkinter.CTkComboBox(options_frame, values=['Yes', 'No'], command=lambda choice, idx=i: self.on_rack_full_change(idx))
            widgets['rack_full_combo'].grid(row=1, column=1, sticky='ew', padx=10, pady=4)
            widgets['rack_full_combo'].set('Yes')

            tk_label = customtkinter.CTkLabel(options_frame, text="Start Coordinate:")
            tk_label.grid(row=2, column=0, sticky='w', pady=4, padx=10)
            widgets['start_coord_entry'] = customtkinter.CTkEntry(options_frame)
            widgets['start_coord_entry'].grid(row=2, column=1, sticky='ew', padx=10, pady=4)

            tk_label = customtkinter.CTkLabel(options_frame, text="End Coordinate:")
            tk_label.grid(row=3, column=0, sticky='w', pady=4, padx=10)
            widgets['end_coord_entry'] = customtkinter.CTkEntry(options_frame)
            widgets['end_coord_entry'].grid(row=3, column=1, sticky='ew', padx=10, pady=4)

            tk_label = customtkinter.CTkLabel(options_frame, text="Rack Barcode:")
            tk_label.grid(row=4, column=0, sticky='w', pady=4, padx=10)
            widgets['rack_barcode_entry'] = customtkinter.CTkEntry(options_frame, placeholder_text="Scan or enter barcode")
            widgets['rack_barcode_entry'].grid(row=4, column=1, sticky='ew', padx=10, pady=4)

            self.nest_widgets.append(widgets)
            self.toggle_nest_inputs(i) # Initially hide options

        # --- Action Buttons Frame (fixed at the bottom of the right frame) ---
        actions_frame = customtkinter.CTkFrame(right_frame, corner_radius=10)
        actions_frame.grid(row=1, column=0, sticky="ew", pady=(10,0))
        actions_frame.grid_columnconfigure(0, weight=1)

        self.start_button = customtkinter.CTkButton(actions_frame, text="Start Process", command=self.start_threads, height=40, font=customtkinter.CTkFont(size=14, weight="bold"),fg_color="#007ACC", hover_color="#005999",text_color="black")
        self.start_button.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 7))
        
        self.pause_resume_button = customtkinter.CTkButton(actions_frame, text="Pause", command=self.toggle_pause_resume, height=40, font=customtkinter.CTkFont(size=14, weight="bold"), text_color="black", state="disabled",fg_color="#3399FF", hover_color="#1F7EE5")
        self.pause_resume_button.grid(row=1, column=0, sticky="ew", padx=15, pady=7)
        
        self.cancel_button = customtkinter.CTkButton(actions_frame, text="Cancel", command=self.cancel_process, height=40, font=customtkinter.CTkFont(size=14, weight="bold"),text_color="black", state="disabled", fg_color="#00C2A8", hover_color="#00A18C")
        self.cancel_button.grid(row=2, column=0, sticky="ew", padx=15, pady=(7, 15))

    def _update_nest_ui(self, index):
        """Centralized method to update a nest's UI elements based on current selections."""
        widgets = self.nest_widgets[index]
        selected_rack_name = widgets['rack_type_combo'].get()
        is_full = widgets['rack_full_combo'].get() == 'Yes'

        widgets['start_coord_entry'].delete(0, "end")
        widgets['end_coord_entry'].delete(0, "end")

        # Populate with defaults if a rack is selected
        if selected_rack_name:
            config = self.rack_configs[selected_rack_name]
            widgets['start_coord_entry'].insert(0, config.get("default_start_coord", "A1"))
            widgets['end_coord_entry'].insert(0, config.get("default_end_coord", ""))

        # Set the final state (disabled or normal) based on the "Is Rack Full?" selection
        final_state = 'disabled' if is_full else 'normal'
        widgets['start_coord_entry'].configure(state=final_state)
        widgets['end_coord_entry'].configure(state=final_state)

    def on_rack_type_change(self, index):
        """Called when a rack type is selected."""
        self.log(f"Nest {index+1}: Rack type changed to {self.nest_widgets[index]['rack_type_combo'].get()}")
        self._update_nest_ui(index)

    def on_rack_full_change(self, index):
        """Called when the 'Is Rack Full' status changes."""
        self.log(f"Nest {index+1}: 'Is Rack Full' changed to {self.nest_widgets[index]['rack_full_combo'].get()}")
        self._update_nest_ui(index)

    def toggle_nest_inputs(self, index):
        """Shows or hides the options for a given nest."""
        widgets = self.nest_widgets[index]
        if widgets['enabled_var'].get():
            widgets['options_frame'].pack(fill='x', expand=True, pady=(0, 10), padx=10)
            widgets['rack_type_combo'].set('Select Rack...') 
            self._update_nest_ui(index)
        else:
            widgets['options_frame'].pack_forget()

    def safe_askretrycancel(self, title, message):
        """Thread-safe way to ask the user to retry or cancel from a background thread."""
        result_queue = queue.Queue()
        def show():
            res = messagebox.askretrycancel(title, message)
            result_queue.put(res)
        self.root.after(0, show)
        return result_queue.get()

    def safe_askokcancel(self, title, message):
        """Thread-safe way to ask the user for ok or cancel from a background thread."""
        result_queue = queue.Queue()
        def show():
            res = messagebox.askokcancel(title, message)
            result_queue.put(res)
        self.root.after(0, show)
        return result_queue.get()

    def log(self, message):
        self.log_queue.put(message)

    def process_log_queue(self):
        """Processes messages from the log queue and displays them."""
        try:
            while not self.log_queue.empty():
                message = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message + '\n')
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
        finally:
            self.root.after(100, self.process_log_queue)

    def send_gchat_notification(self, event_message, user_name, csv_filepath=None, log_filepath=None):
        """Sends a notification to a Google Chat space via webhook."""
        if not self.gchat_webhook_url or self.gchat_webhook_url == "YOUR_GCHAT_WEBHOOK_URL_HERE":
            self.log("G-Chat notification skipped: Webhook URL not configured.")
            return

        message = f"ANUBIS System Alert:\n\n*User:* {user_name}@calicolabs.com\n*Event:* {event_message}"
        if csv_filepath:
            message += f"\n*Data File:* `{csv_filepath}`"
        if log_filepath:
            message += f"\n*Log File:* `{log_filepath}`"

        payload = {"text": message}

        try:
            response = requests.post(self.gchat_webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            self.log("G-Chat notification sent successfully.")
        except requests.exceptions.RequestException as e:
            self.log(f"Failed to send G-Chat notification: {e}")

    def save_log_to_file(self, base_filename="Completed_Run"):
        """Saves the current content of the log widget to a file."""
        log_content = self.log_text.get("1.0", tk.END)
        file_path = self.common_params["LOG_FILE_PATH"]
        os.makedirs(file_path, exist_ok=True)
        
        timestamp_str = datetime.now().strftime("%Y.%m.%d_%H.%M")
        log_filename = os.path.join(file_path, f"{timestamp_str}_{base_filename}.log")
        
        try:
            with open(log_filename, 'w', encoding='utf-8') as f:
                f.write(log_content)
            self.log(f"System log saved to: {log_filename}")
            return log_filename
        except IOError as e:
            self.log(f"Error saving log file: {e}")
            return None

    def start_threads(self):
        user_name = self.user_name_entry.get().strip()
        if not user_name:
            messagebox.showerror("Input Error", "Please enter your name before starting the process.")
            return

        if not self.rack_configs:
            messagebox.showerror("Config Error", "Cannot start: No rack configurations loaded. Check file path and logs.")
            return

        tasks = []
        for i, widgets in enumerate(self.nest_widgets):
            if widgets['enabled_var'].get():
                selected_rack_name = widgets['rack_type_combo'].get()
                if not selected_rack_name:
                    messagebox.showerror("Input Error", f"Please select a rack type for {widgets['name']}.")
                    return
                
                config = self.rack_configs[selected_rack_name]
                max_wells = config.get("max_wells", 96)
                reset_interval = config.get("row_reset_interval", 8)

                start_coord = widgets['start_coord_entry'].get()
                end_coord = widgets['end_coord_entry'].get()
                start_index = coordinate_to_index(start_coord, max_wells, reset_interval)
                end_index = coordinate_to_index(end_coord, max_wells, reset_interval)
                rack_barcode = widgets['rack_barcode_entry'].get()
                
                if not rack_barcode.strip():
                    messagebox.showerror("Input Error", f"Please enter a rack barcode for {widgets['name']}.")
                    return
                if start_index == -1 or end_index == -1 or end_index < start_index:
                    messagebox.showerror("Coordinate Error", f"Please check the coordinates for {widgets['name']}. They may be invalid for the selected rack type.")
                    return
                
                base_pose_key = f"base_pose_{widgets['name'].lower().replace(' ', '_')}"
                base_pose = config.get(base_pose_key)
                if not base_pose:
                    messagebox.showerror("Config Error", f"The config '{selected_rack_name}' is missing '{base_pose_key}'.")
                    return

                task_params = {**config, **self.common_params, "name": widgets['name'], "base_pose": base_pose, "start_index": start_index, "end_index": end_index, "rack_barcode": rack_barcode}
                tasks.append(task_params)

        if not tasks:
            messagebox.showwarning("No Tasks", "Please enable and configure at least one nest.")
            return
        
        # Send starting notification
        self.send_gchat_notification("Process Started", user_name)

        # Disable UI components
        self.user_name_entry.configure(state=tk.DISABLED)
        for widgets in self.nest_widgets:
            widgets['enable_check'].configure(state=tk.DISABLED)
            widgets['rack_type_combo'].configure(state=tk.DISABLED)
            widgets['rack_full_combo'].configure(state=tk.DISABLED)
            widgets['start_coord_entry'].configure(state=tk.DISABLED)
            widgets['end_coord_entry'].configure(state=tk.DISABLED)
            widgets['rack_barcode_entry'].configure(state=tk.DISABLED)

        self.cancel_event.clear(); self.pause_event.set()
        self.start_button.configure(state=tk.DISABLED)
        self.pause_resume_button.configure(state=tk.NORMAL, text="Pause")
        self.cancel_button.configure(state=tk.NORMAL)
        
        self.scanner_listener = BarcodeScannerListener(self.barcode_queue)
        self.scanner_thread = threading.Thread(target=self.scanner_listener.start_listening, daemon=True)
        self.scanner_thread.start()
        
        self.robot_thread = threading.Thread(target=self.robot_task, args=(tasks, user_name), daemon=True)
        self.robot_thread.start()

    def toggle_pause_resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear(); self.log("--- PROCESS PAUSED ---"); self.pause_resume_button.configure(text="Resume")
        else:
            self.pause_event.set(); self.log("--- PROCESS RESUMED ---"); self.pause_resume_button.configure(text="Pause")

    def cancel_process(self):
        self.log("!!! CANCEL REQUESTED BY USER !!!"); self.pause_event.set(); self.cancel_event.set()
        self.cancel_button.configure(state=tk.DISABLED, text="Cancelling...")
        self.pause_resume_button.configure(state=tk.DISABLED)

    def emergency_shutdown(self):
        self.log("!!!!!!!! EMERGENCY SHUTDOWN INITIATED !!!!!!!!")
        self.pause_event.set(); self.cancel_event.set()
        if self.robot and self.robot.IsConnected():
            self.robot.DeactivateRobot(); self.robot.Disconnect()
            self.log("-> Robot deactivated and disconnected forcefully.")
        self.task_completed()

    def task_completed(self):
        # Re-enable UI components
        self.user_name_entry.configure(state=tk.NORMAL)
        for i, widgets in enumerate(self.nest_widgets):
            widgets['enable_check'].configure(state=tk.NORMAL)
            if widgets['enabled_var'].get():
                widgets['rack_type_combo'].configure(state='readonly')
                widgets['rack_full_combo'].configure(state='readonly')
                widgets['rack_barcode_entry'].configure(state='normal')
                self._update_nest_ui(i)  # This handles the coordinate entries

        self.start_button.configure(state=tk.NORMAL)
        self.pause_resume_button.configure(state=tk.DISABLED, text="Pause")
        self.cancel_button.configure(state=tk.DISABLED, text="Cancel")
        if self.scanner_listener:
            self.scanner_listener.stop(); self.scanner_listener = None
        self.log("Scanner listener stopped.")


    def show_help_popup(self, parent_popup):
        """Creates a non-modal popup with detailed help information."""
        help_popup = tk.Toplevel(parent_popup)
        help_popup.title("Help: Why Did The Arm Error?")
        help_popup.configure(bg='#f0f0f0')

        # --- Popup centering ---
        parent_x = parent_popup.winfo_x()
        parent_y = parent_popup.winfo_y()
        parent_w = parent_popup.winfo_width()
        parent_h = parent_popup.winfo_height()
        popup_w = 600
        popup_h = 650
        pos_x = parent_x + (parent_w // 2) - (popup_w // 2)
        pos_y = parent_y + (parent_h // 2) - (popup_h // 2)
        help_popup.geometry(f'{popup_w}x{popup_h}+{pos_x}+{pos_y}')

        # --- Content Frame ---
        content_frame = tk.Frame(help_popup, bg='#f0f0f0', padx=15, pady=15)
        content_frame.pack(expand=True, fill=tk.BOTH)

        # --- Fonts ---
        title_font = font.Font(family="Arial", size=12, weight="bold")
        subtitle_font = font.Font(family="Arial", size=10, weight="bold")
        body_font = font.Font(family="Arial", size=9)

        # --- Helper to create text blocks (Corrected) ---
        def create_text_block(parent, text, font, is_bullet=False, pack_pady=(2, 0), **kwargs):
            """
            Creates and packs a text label.
            'pack_pady' is separated from other kwargs to be used specifically for the .pack() method.
            Other kwargs (like 'fg' for color) are passed to the Label constructor.
            """
            prefix = "•  " if is_bullet else ""
            label = tk.Label(parent, text=prefix + text, font=font, wraplength=550, justify=tk.LEFT, bg='#f0f0f0', **kwargs)
            label.pack(anchor="w", pady=pack_pady)

        # --- Help Content ---
        tk.Label(content_frame, text="Why Did The Arm Error?", font=title_font, bg='#f0f0f0').pack(anchor="w", pady=(0, 10))

        # Section 1
        create_text_block(content_frame, "Ensure Robot is not being controlled by another UI:", subtitle_font, pack_pady=(5,2))
        create_text_block(content_frame, "Program will not run if arm is connected to another UI.", body_font, is_bullet=True)

        # Section 2
        create_text_block(content_frame, "Check your nest settings for your vial rack:", subtitle_font, pack_pady=(5,2))
        create_text_block(content_frame, "They may be improperly set up causing the arm to reach for a position out of its range.", body_font, is_bullet=True)
        create_text_block(content_frame, "These are the X and Y increments for each nesting location in your JSON file.", body_font, is_bullet=True)
        create_text_block(content_frame, "Other possible errors may be within the JSON file as well. Cross-check with other files.", body_font, is_bullet=True)

        # Section 3
        create_text_block(content_frame, "Torque exceeded the set maximum:", subtitle_font, pack_pady=(15,2))
        create_text_block(content_frame, "Vial rack misaligned causing the arm to crash.", body_font, is_bullet=True)
        create_text_block(content_frame, "Vial dropped in a bad location causing the arm to crash into it.", body_font, is_bullet=True)
        create_text_block(content_frame, "Vial stuck in scale holder causing the arm to crash.", body_font, is_bullet=True)
        create_text_block(content_frame, "Scale base misaligned forcing improper placement of vials.", body_font, is_bullet=True)
        create_text_block(content_frame, "Scale moved from based position causing misalignment.", body_font, is_bullet=True)

        # Section 4
        create_text_block(content_frame, "Should arm not reset from 'Reset Robot Error' Button, the Meca500 API must be used:", subtitle_font, pack_pady=(15,2))
        create_text_block(content_frame, "A Red popup on top middle of the API screen will have a 'Reset Error'.", body_font, is_bullet=True)
        create_text_block(content_frame, "Press that button. Then, at the top right, find the 'monitor' icon (eyeball or paperclip) next to the 'home' button and switch from 'Monitor' to 'Control'.", body_font, is_bullet=True)
        create_text_block(content_frame, "Press the 'Home' button (may look like a lightning symbol if deactivated) to home the arm.", body_font, is_bullet=True)
        create_text_block(content_frame, "On the bottom left, click the Target button and press 'Zero All Joints'.", body_font, is_bullet=True)
        create_text_block(content_frame, "!!!!!! ENSURE THERE IS NOTHING IN THE ARM'S WAY WHEN ZEROING JOINTS !!!!!!", body_font, is_bullet=True, fg="red")
        create_text_block(content_frame, "If the arm is in the scale, open the doors and remove the front panel before zeroing.", body_font, is_bullet=True)
        create_text_block(content_frame, "Once zeroing is complete, switch 'Control' back to 'Monitor' mode.", body_font, is_bullet=True)

        # --- Close Button ---
        close_button = tk.Button(content_frame, text="Close", command=help_popup.destroy, bg="#cccccc", fg='black', font=("Arial", 10))
        close_button.pack(pady=(20, 0))

        # --- Non-Modal Setup ---
        # Makes the help window stay on top of its parent but does not block it.
        help_popup.transient(parent_popup)

    def show_error_popup(self):
        """Creates a modal popup that runs the reset in a separate thread."""
        popup = tk.Toplevel(self.root)
        popup.title("Robot Error")

        # --- Popup centering and styling ---
        # Let the widgets determine the height automatically to reduce whitespace
        popup.grid_columnconfigure(0, weight=1)
        popup.configure(bg='#f0f0f0')

        # --- Main Message ---
        message = "Arm has encountered an error. Please reset:"
        tk.Label(popup, text=message, wraplength=380, justify=tk.LEFT, bg='#f0f0f0', font=("Arial", 10)).grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        # --- Button 2: Reset Robot Error (Threaded) ---
        robot_resetter = Meca500Resetter()
        
        def run_reset_sequence(button):
            """This function will be run in the new thread to prevent UI freezing."""
            print("Starting robot reset in a background thread...")
            button.config(state=tk.DISABLED, text="Resetting...")
            success = robot_resetter.reset_and_home()
            if success:
                button.config(text="Reset Successful!", bg="#4CAF50") # Green for success
            else:
                button.config(state=tk.NORMAL, text="Reset Failed. Try Again.", bg="#f44336") # Red for failure

        reset_button = tk.Button(
            popup,
            text="Reset Robot Error",
            bg="#2E6CF3",
            fg='white',
            font=("Arial", 10, "bold")
        )
        # Pass the button itself to the command
        reset_button.config(command=lambda: threading.Thread(target=run_reset_sequence, args=(reset_button,), daemon=True).start())
        reset_button.grid(row=1, column=0, padx=10, pady=10, ipady=4, ipadx=10)

        # UI/Help Buttons ---
        ui_label = tk.Label(
            popup,
            text="If reset fails, use the robot's web interface or see help:",
            justify=tk.LEFT,
            bg='#f0f0f0',
            font=("Arial", 9)
        )
        ui_label.grid(row=2, column=0, padx=10, pady=(10, 0), sticky="w")

        # --- Frame to hold the bottom buttons ---
        button_frame = tk.Frame(popup, bg="#f0f0f0")
        # Make the frame span the entire width of the popup
        button_frame.grid(row=3, column=0, padx=10, pady=(5, 15), sticky="ew")

        # Configure the grid inside the frame to position the buttons
        # Column 0 (weight 1) acts as a left spacer
        # Column 1 (weight 0) holds the center button
        # Column 2 (weight 1) acts as a right spacer and holds the right button
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=0)
        button_frame.grid_columnconfigure(2, weight=1)

        # --- Button 1: Go to UI (Center) ---
        def open_ui():
            """Opens the robot UI in a web browser without closing the popup."""
            webbrowser.open("http://192.168.0.100/")

        ui_button = tk.Button(button_frame, text="Go to Robot UI", command=open_ui, bg="#D1001C", fg='white', font=("Arial", 10))
        # Place the button in the center column of the frame's grid
        ui_button.grid(row=0, column=1)

        # --- Help Button (Right) ---
        help_button = tk.Button(button_frame, text="Help", command=lambda: self.show_help_popup(popup), bg="#242222", fg='white', font=("Arial", 10))
        # Place the button in the rightmost column and align it to the east (right)
        help_button.grid(row=0, column=2, sticky="e")
        
        # --- Center the popup on the root window ---
        popup.update_idletasks() # Update widgets to get correct size
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        popup_w = popup.winfo_width()
        popup_h = popup.winfo_height()
        pos_x = root_x + (root_w // 2) - (popup_w // 2)
        pos_y = root_y + (root_h // 2) - (popup_h // 2)
        popup.geometry(f'+{pos_x}+{pos_y}')


        # --- Modal and Wait for the main error popup ---
        popup.transient(self.root)
        popup.grab_set()
        self.root.wait_window(popup)


    def robot_task(self, tasks, user_name):
        self.cycle_count = 0  # for checking if the scale needs an adjustment every x cycles
        self.robot = mdr.Robot() # sets classes to be called on
        self.arduino = ArduinoController(port=self.common_params["ARDUINO_PORT"], baudrate=115200)
        self.scale = MettlerToledoController(port=self.common_params["SCALE_PORT"], log_callback=self.log,arduino_controller=self.arduino, app_instance=self)
        csv_filepath = None
        
        def check_for_events():
            self.pause_event.wait()
            if self.cancel_event.is_set(): raise ProcessCancelledError("Process cancelled by user.")
            
        def smart_sleep(duration):
            start = time.time()
            while time.time() - start < duration:
                check_for_events()
                time.sleep(min(0.1, duration - (time.time() - start)))

        try:
            self.log(f"Connecting..."); self.robot.Connect(address=self.common_params["ROBOT_IP"]); check_for_events()
            self.robot.ActivateRobot(); check_for_events()
            self.robot.Home(); check_for_events()
            self.log("-> Robot Homed and Activated.")

            torque_limit = 50  # reduces force required to error to minimize damage if it hits something
            self.robot.SetTorqueLimitsCfg(4, 1) # Error on torque limit, detect always
            self.robot.SetTorqueLimits(torque_limit, torque_limit, torque_limit, torque_limit, torque_limit, torque_limit)
            self.log(f"-> Torque limits set to {torque_limit}% for all joints.")
            # SetJointVel: specifies desired velocity of joints during MovePose and MoveJoints commands
            # SetJointAcc: sets acc limit of MovePose and MoveJoints
            # SetCartLinVel: sets desird and max velocity of MovLin Movemennts
            self.robot.SetJointVel(80); self.robot.SetJointAcc(75); self.robot.SetCartLinVel(400) 


            self.log("Connecting to and initializing the scale...")
            if not self.scale.connect():
                raise ConnectionError("Failed to connect to the Mettler Toledo scale.")
            check_for_events()
            
            self.scale.power_on_or_reset()
            self.scale.zero()
            check_for_events()
            self.log("-> Scale Initialized and Zeroed.")
            
            for nest_params in tasks:
                self.log(f"\n********** STARTING {nest_params['name']} with {nest_params['rack_name']} **********"); check_for_events()
                
                # On starting a Nest 3 task, move to the safety position first.
                if nest_params['name'] == 'Nest 3':
                    self.log("   -> Moving to Nest 3 safety position to begin task.")
                    self.robot.MoveJoints(*nest_params['intermediate_pose_nest3_safety'])
                    self.robot.WaitIdle()
                    check_for_events()

                # Json parameters and position parameters
                ZERO_INT = nest_params.get('row_reset_interval', 6)
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
                scale_dropoff = nest_params.get("scale_dropoff", [-0.768729, 262.21615, 130, -90, -0.16875, 90])
                scale_pickup = nest_params.get("scale_pickup", [-0.768729, 262.21615, 127, -90, -0.16875, 90])
                MAX_WELLS = nest_params.get('max_wells', 96)
                RETRY_APPROACH_MM = nest_params.get('retry_approach_mm', 10)
                RACK_NAME = nest_params.get('file_label')
                base_pose = nest_params['base_pose']
                home_position_joints = nest_params['home_position_joints']

                dynamic_scanner_pose = list(nest_params['scanner_pose']) #changes scanner z based on json
                if 'scanner_z_position' in nest_params:
                    dynamic_scanner_pose[2] = nest_params['scanner_z_position']
                    self.log(f"   -> Using custom scanner Z-position: {dynamic_scanner_pose[2]}")

                self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); check_for_events()

                file_path = nest_params["CSV_FILE_PATH"]
                rack_barcode = nest_params["rack_barcode"]
                timestamp_str = datetime.now().strftime("%Y.%m.%d_%H.%M")
                csv_filepath = os.path.join(file_path, f"{RACK_NAME}_{rack_barcode}_{timestamp_str}.csv")
                os.makedirs(file_path, exist_ok=True)
                
                with open(csv_filepath, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    if os.path.getsize(csv_filepath) == 0: writer.writerow(self.scanner_params["CSV_HEADER"])
                    
                    start_index, end_index = nest_params["start_index"], nest_params["end_index"]
                    last_completed_pose = None

                    for i in range(start_index, end_index + 1):
                        self.log(f"--- CYCLE for Vial {index_to_coordinate(i, MAX_WELLS, RESET_INTERVAL)} ({nest_params['name']}) ---"); check_for_events()
                        
                        group_number, step_in_group = divmod(i, RESET_INTERVAL)
                        current_target_pose = list(base_pose)
                        
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

                        scale_dropoff_approach = list(scale_dropoff); scale_dropoff_approach[2] = 200
                        scale_pickup_approach = list(scale_pickup); scale_pickup_approach[2] = 200

                        approach_pose = list(current_target_pose); approach_pose[2] += LIFT_UP_MM
                        retry_approach_pose = list(current_target_pose); retry_approach_pose[2] += RETRY_APPROACH_MM
                       
                        if last_completed_pose is not None:
                            lift_off_pose = list(last_completed_pose); lift_off_pose[2] += LIFT_UP_MM
                            self.robot.MoveLin(*lift_off_pose); self.robot.WaitIdle(); check_for_events()

                        self.robot.MovePose(*approach_pose); self.robot.WaitIdle(); check_for_events()
                        self.robot.MoveLin(*current_target_pose); self.robot.WaitIdle(); check_for_events()
                        self.robot.MoveGripper(GRIPPER_CLOSE); self.robot.WaitIdle(); check_for_events() 

                        
                        self.robot.MoveLin(*approach_pose); self.robot.WaitIdle(); check_for_events()

                        # MoveLin is for precision movements that require a straight path
                        # MovePose is for path movements that dont need to be perfect as they tend to have curvature in the movement
                        # MoveJoints tells the joint was angles to be in rather than a coordinate

                        # If leaving from Nest 3, move to a specific safety pose first.
                        if nest_params['name'] == 'Nest 3':
                            self.log("   -> Moving to Nest 3 safety position before proceeding.")
                            self.robot.MoveJoints(*nest_params['intermediate_pose_nest3_safety'])
                            self.robot.WaitIdle()
                            check_for_events()

                        self.robot.MoveJoints(*home_position_joints); self.robot.WaitIdle(); check_for_events()
                        self.robot.MovePose(*dynamic_scanner_pose); self.robot.WaitIdle(); check_for_events()
                        
                        scanned_barcode = None
                        try: ## if he scan fails it drops the vial back off in it original spot and picks it back up to try and scan again
                            self.log("   -> Waiting for barcode scan (Attempt 1/2)...")
                            scanned_barcode = self.barcode_queue.get(timeout=4)
                        except queue.Empty:
                            self.log("   -> Scan timed out. Returning vial to re-grip for second attempt.")
                            
                            self.robot.MoveJoints(*home_position_joints); self.robot.WaitIdle(); check_for_events()
                            
                            if nest_params['name'] == 'Nest 3':
                                self.log("   -> (Retry) Moving to Nest 3 safety position before re-gripping.")
                                self.robot.MoveJoints(*nest_params['intermediate_pose_nest3_safety'])
                                self.robot.WaitIdle()
                                check_for_events()
                            
                            self.robot.MovePose(*approach_pose); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveLin(*retry_approach_pose); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); check_for_events(); 
                            self.robot.MoveLin(*current_target_pose); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveGripper(GRIPPER_CLOSE); self.robot.WaitIdle(); check_for_events(); smart_sleep(.2)

                              
                        
                            self.robot.MoveLin(*approach_pose); self.robot.WaitIdle(); check_for_events()
                            
                            if nest_params['name'] == 'Nest 3':
                                self.log("   -> (Retry) Moving to Nest 3 safety position before proceeding to scanner.")
                                self.robot.MoveJoints(*nest_params['intermediate_pose_nest3_safety'])
                                self.robot.WaitIdle()
                                check_for_events()

                            self.robot.MoveJoints(*home_position_joints); self.robot.WaitIdle(); check_for_events()
                            self.robot.MovePose(*dynamic_scanner_pose); self.robot.WaitIdle(); check_for_events()
                            
                            try:  ### if the scan fails a second time then it puts it backin its original spot and got to the next position
                                self.log("   -> Waiting for barcode scan (Attempt 2/2)...")
                                scanned_barcode = self.barcode_queue.get(timeout=4)
                            except queue.Empty:
                                self.log("   -> Scan failed on second attempt. Returning vial and skipping.")

                                self.robot.MoveJoints(*home_position_joints); self.robot.WaitIdle(); check_for_events()
                                
                                if nest_params['name'] == 'Nest 3':
                                    self.log("   -> (Failed Scan) Moving to Nest 3 safety position before returning vial.")
                                    self.robot.MoveJoints(*nest_params['intermediate_pose_nest3_safety'])
                                    self.robot.WaitIdle()
                                    check_for_events()

                                self.robot.MovePose(*approach_pose); self.robot.WaitIdle(); check_for_events()
                                self.robot.MoveLin(*retry_approach_pose); self.robot.WaitIdle(); check_for_events()
                                self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); check_for_events()

                                vial_coordinate = index_to_coordinate(i, MAX_WELLS, RESET_INTERVAL)
                                writer.writerow([vial_coordinate, "Vial Not Found"]); csvfile.flush()
                                self.root.after(0, self.send_gchat_notification, f"Vial not found at {nest_params['name']} - {vial_coordinate}", user_name)
                                last_completed_pose = current_target_pose
                                continue 

                        if scanned_barcode:

                            # Increment cycle counter at the start of a valid cycle, Starts process with an adjustment check
                            self.cycle_count += 1
                            self.log(f"--- Starting Cycle #{self.cycle_count} ---")

                            # Check if it's time for a scale adjustment
                            if self.cycle_count == 1 or self.cycle_count % 10 == 0:
                               self.log(f"Cycle {self.cycle_count} is a multiple of 10. Performing scale adjustment check.")
                               if not self.scale.scale_adjustment_check(self, user_name):
                                   # Define the message for the user
                                   popup_message = "Manual scale adjustment required.\n\nPress OK when completed, or Cancel to stop the process."
                                   # Log the event and send a notification
                                   self.log(popup_message)
                                   self.root.after(0, self.send_gchat_notification, "Manual scale adjustment required. Process is paused.", user_name)
                                   # PAUSE and show a popup. Code execution will stop here until the user clicks "OK".
                                   user_choice = self.safe_askokcancel("Manual Adjustment Required 🔧", popup_message)
                                   # Handle the choice. If user clicks "Cancel" (user_choice is False)...
                                   if not user_choice:
                                     cancel_message = "Process cancelled by user during manual scale adjustment."
                                     self.log(cancel_message)
                                     self.root.after(0, self.send_gchat_notification, cancel_message, user_name)
                                     raise ProcessCancelledError(cancel_message)
                            self.log("Scale adjustment check complete. Resuming operations.")
                            check_for_events() # Assuming you want to check for events after this pause

                            # One-time tare before loading the first vial
                            if self.cycle_count == 1:
                                self.log("Closing doors to prepare for one-time initial tare...")
                                if not self.scale.close_doors(self, user_name):
                                    raise ProcessCancelledError("process ended due to door failure.") 
                                check_for_events(); smart_sleep(1)
                                
                                if not self.scale.tare():
                                    self.log("Warning: Initial tare operation failed. Proceeding, but weight may be inaccurate.")
                                check_for_events(); smart_sleep(1)
                            
                            vial_coordinate = index_to_coordinate(i, MAX_WELLS, RESET_INTERVAL)
                            self.log(f"   -> Scan received: {scanned_barcode} for vial {vial_coordinate}. Resuming...")
                            
                            self.robot.MovePose(*nest_params['intermediate_pose_2']); self.robot.WaitIdle(); check_for_events()
                            self.robot.MovePose(*nest_params['intermediate_pose_3']); self.robot.WaitIdle(); check_for_events()

                            # if doors don't open process will be canceled -- this is just a last resort as the function has many error precautions
                            if not self.scale.open_doors(self, user_name):
                              raise ProcessCancelledError("Process ended due to door failure.") 
                            check_for_events()

                            # Moves vial into scale
                            # I put a timestamp here as an inital time test for opening the doors but now i left it just to see how long it takes to cycle through
                            self.robot.MovePose(*scale_dropoff_approach); self.robot.WaitIdle(); check_for_events(); self.log(f"Arm started moving ... Timestamp: {datetime.now().time()}")
                            self.robot.SetCartLinVel(50) ## Drastically reduce speed inside draft shield to prevent aerodynamic turbulence
                            self.robot.MoveLin(*scale_dropoff); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); check_for_events(); smart_sleep(.5)
                            self.robot.MoveLin(*scale_dropoff_approach); self.robot.WaitIdle(); check_for_events()
                            self.robot.SetCartLinVel(400) ## Restore travel speed
                            self.robot.MovePose(*nest_params['intermediate_pose_3']); self.robot.WaitIdle(); check_for_events()

                            if not self.scale.close_doors(self, user_name):
                              raise ProcessCancelledError("User chose to end the process due to door failure.")
                            check_for_events()
                            self.log("Waiting 3 seconds for air currents and vibrations to settle...")
                            smart_sleep(3) # Increased settling time for higher precision

                            # get a stable weight
                            stable_weight, stable_unit = self.scale.get_stable_weight();check_for_events()
                            #If the initial attempt fails, start the recovery and retry loop
                            if stable_weight is None:
                                log_message = "Initial weight measurement failed. Starting recovery process."
                                self.log(log_message)
                                self.root.after(0, self.send_gchat_notification, log_message, user_name)
                                                            
                                while True: # This loop handles retries prompted by the user
                                    # --------------------------------------------------------------------
                                    # A. RECOVERY SEQUENCE: Pick up vial, reset scale, place vial back
                                    # --------------------------------------------------------------------
                                    self.log("   -> Picking up vial to reset scale...")

                                    if not self.scale.open_doors(self, user_name):
                                        raise ProcessCancelledError("Process ended due to door failure.")
                                    check_for_events()

                                    self.robot.MovePose(*scale_pickup_approach); self.robot.WaitIdle(); check_for_events()
                                    self.robot.SetCartLinVel(50) ## Drastically reduce speed inside draft shield
                                    self.robot.MoveLin(*scale_pickup); self.robot.WaitIdle(); check_for_events()
                                    self.robot.MoveGripper(GRIPPER_CLOSE); self.robot.WaitIdle(); check_for_events(); smart_sleep(.5)
                                    self.robot.MoveLin(*scale_pickup_approach); self.robot.WaitIdle(); check_for_events()
                                    self.robot.SetCartLinVel(400) ## Restore travel speed
                                    self.robot.MovePose(*nest_params['intermediate_pose_3']); self.robot.WaitIdle(); check_for_events()

                                    if not self.scale.close_doors(self, user_name):
                                        raise ProcessCancelledError("User chose to end the process due to door failure.")
                                    check_for_events(); smart_sleep(1)

                                    self.log("   -> Resetting the scale...")
                                    self.scale.power_on_or_reset(); check_for_events()
                                    self.scale.tare(); check_for_events()

                                    if not self.scale.open_doors(self, user_name):
                                        raise ProcessCancelledError("Process ended due to door failure.")
                                    check_for_events()

                                    self.log("   -> Placing vial back on the scale...")
                                    self.robot.MovePose(*scale_dropoff_approach); self.robot.WaitIdle(); check_for_events()
                                    self.robot.SetCartLinVel(50) ## Drastically reduce speed inside draft shield
                                    self.robot.MoveLin(*scale_dropoff); self.robot.WaitIdle(); check_for_events()
                                    self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); check_for_events(); smart_sleep(.5)
                                    self.robot.MoveLin(*scale_dropoff_approach); self.robot.WaitIdle(); check_for_events()
                                    self.robot.SetCartLinVel(400) ## Restore travel speed
                                    self.robot.MovePose(*nest_params['intermediate_pose_3']); self.robot.WaitIdle(); check_for_events()

                                    if not self.scale.close_doors(self, user_name): # Corrected call
                                        raise ProcessCancelledError("User chose to end the process due to door failure.")
                                    check_for_events()
                                    self.log("Waiting 3 seconds for air currents and vibrations to settle...")
                                    smart_sleep(3) # Increased settling time for higher precision                                    
                                    # --------------------------------------------------------------------
                                    # B. RETRY WEIGHING: Attempt to get weight after recovery
                                    # --------------------------------------------------------------------
                                    self.log("   -> Retrying to get stable weight after reset...")
                                    stable_weight, stable_unit = self.scale.get_stable_weight()
                                    check_for_events()

                                    if stable_weight is not None:
                                        log_message = "Stable weight obtained. Reset successful"
                                        self.log(log_message)
                                        self.root.after(0, self.send_gchat_notification, log_message, user_name)
                                        break # Success! Exit the recovery loop.

                                   # C. PROMPT USER: If retry fails, ask the user what to do
                                    # --------------------------------------------------------------------
                                    self.log("  <- Failed to get stable weight after recovery. Prompting user...")
                                    # 1. Define the message and send a GChat notification
                                    popup_title = "Weighing Failed"
                                    popup_message = "Could not get a stable weight after resetting the scale.\n\nDo you want to retry the entire recovery process?"
                                    notification_message = "Weighing failed after recovery. Process is paused pending user input."
                                    self.root.after(0, self.send_gchat_notification, notification_message, user_name)
                                    # 2. Show the popup and wait for the user's choice
                                    should_retry = self.safe_askretrycancel(popup_title, popup_message)
                                    # 3. Handle the user's choice
                                    if should_retry:
                                        # If the user clicks "Retry", log it and the 'while' loop will continue.
                                        self.log("-> User chose to RETRY the recovery process.")
                                    else:
                                        # If the user clicks "Cancel", log it and raise an error to stop everything.
                                        cancel_message = "User cancelled the process after failed weight measurement."
                                        self.log(f"!!! {cancel_message}")
                                        self.root.after(0, self.send_gchat_notification, cancel_message, user_name)
                                        raise ProcessCancelledError(cancel_message)
                                    # If the code reaches this point, the user chose to retry, and the loop continues.
                            # 3. Write data to CSV 
                            vial_coordinate = index_to_coordinate(i, MAX_WELLS, RESET_INTERVAL)
                            writer.writerow([vial_coordinate, scanned_barcode, f"{stable_weight:.5f}" if stable_weight is not None else "N/A", stable_unit or "N/A"])
                            csvfile.flush()

                            if not self.scale.open_doors(self, user_name):
                              raise ProcessCancelledError("User chose to end the process due to door failure.") 
                            check_for_events()
                            
                            #picks vial up from scale and moves back to original postion
                            self.robot.MovePose(*scale_pickup_approach); self.robot.WaitIdle(); check_for_events()
                            self.robot.SetCartLinVel(50) ## Drastically reduce speed inside draft shield
                            self.robot.MoveLin(*scale_pickup); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveGripper(GRIPPER_CLOSE); self.robot.WaitIdle(); check_for_events(); smart_sleep(.5)                            
                            self.robot.MoveLin(*scale_pickup_approach); self.robot.WaitIdle(); check_for_events()
                            self.robot.SetCartLinVel(400) ## Restore travel speed
                            self.robot.MovePose(*nest_params['intermediate_pose_3']); self.robot.WaitIdle(); check_for_events()
                            
                            # Close doors and tare the scale for the NEXT vial to increase speed
                            self.log("Closing doors and taring scale for the next vial...")
                            if not self.scale.close_doors(self, user_name):
                                raise ProcessCancelledError("User chose to end the process due to door failure.")
                            check_for_events(); smart_sleep(1)
                            if not self.scale.tare():
                                self.log("Warning: Tare operation failed. Proceeding, but weight may be inaccurate.")
                            check_for_events(); smart_sleep(1)

                            self.robot.MovePose(*nest_params['intermediate_pose_2']); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveJoints(*home_position_joints); self.robot.WaitIdle(); check_for_events()

                            if nest_params['name'] == 'Nest 3':
                                self.log("   -> Moving to Nest 3 safety position before returning vial from scale.")
                                self.robot.MoveJoints(*nest_params['intermediate_pose_nest3_safety'])
                                self.robot.WaitIdle()
                                check_for_events()

                            self.robot.MovePose(*approach_pose); self.robot.WaitIdle(); check_for_events()
                            self.robot.SetCartLinVel(400)
                            self.robot.MoveLin(*current_target_pose); self.robot.WaitIdle(); check_for_events()
                            self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle(); check_for_events()

                            last_completed_pose = self.robot.GetPose()
                            self.log("   -> Cycle complete.\n"); smart_sleep(.5)

                    if last_completed_pose is not None:
                        self.log(f"-> Finished rack {nest_params['name']}. Lifting up before next task.")
                        lift_off_pose = list(last_completed_pose); lift_off_pose[2] += LIFT_UP_MM
                        self.robot.MoveLin(*lift_off_pose); self.robot.WaitIdle(); check_for_events()

            self.log("***** All selected tasks are complete. *****")
            self.robot.MoveJoints(*self.common_params['home_position_joints']); self.robot.WaitIdle()
            self.log("-> Robot is at final home position.")
            log_filepath = self.save_log_to_file()
            self.scale.close_doors(self, user_name)
            self.root.after(0, self.send_gchat_notification, "Process completed successfully", user_name, csv_filepath, log_filepath)
        
        ### error safe postion and move back to home
        except ProcessCancelledError as e:
            self.log(str(e)); self.log("Aborting process...")
            log_filepath = self.save_log_to_file("cancelled_process")
            self.root.after(0, self.send_gchat_notification, "Process was cancelled by the user", user_name, csv_filepath, log_filepath)
            if self.robot and self.robot.IsConnected():
                try:
                    self.robot.WaitIdle()
                    self.log("Opening gripper...");
                    self.robot.MoveGripper(GRIPPER_OPEN); self.robot.WaitIdle()
                    current_joints = self.robot.GetJoints()
                    self.log(f"Current joints: {[f'{j:.2f}' for j in current_joints]}")
                    cancel_pose_1 = [current_joints[0], -25.96, 64.97, -0.83, -40.07, -2.39]  ## safety positon 
                    cancel_pose_2 = [0, -25.96, 64.97, -0.83, -40.07, -2.39]
                    self.log(f"Moving to intermediate cancel pose (J1={current_joints[0]:.2f})...")
                    self.robot.MoveJoints(*cancel_pose_1); self.robot.WaitIdle()
                    self.log("Moving J1 to 0...")
                    self.robot.MoveJoints(*cancel_pose_2); self.robot.WaitIdle()
                    self.log("Moving to final home position...")
                    self.robot.MoveJoints(*self.common_params["home_position_joints"]); self.robot.WaitIdle()
                    self.log("-> Robot returned to home position safely.")
                except mdr.MecademicException as move_err:
                    self.log(f"Could not perform safe return after cancel: {move_err}")
        except Exception as e:
            error_message = f"Robot has errored due crash or incorrect labware definitions. User involvement necessary: {e}"
            self.log(f"\n!!!!!!!! AN ERROR OCCURRED/ ARM HAS CRASHED !!!!!!!!\n{e}\n")
            log_filepath = self.save_log_to_file("incomplete_log")
            self.root.after(0, self.send_gchat_notification, f"ROBOT ERROR: {error_message}", user_name, csv_filepath, log_filepath)
            self.root.after(0, self.show_error_popup)

        finally:
         # Disconnect Robot
         if self.robot and self.robot.IsConnected():
           self.log("Disconnecting robot..."); self.robot.DeactivateRobot(); self.robot.Disconnect(); self.log("-> Disconnected.")
         # Disconnect Scale
         if self.scale and self.scale.connection:
             self.log("Disconnecting Scale..."); self.scale.close_doors(self, user_name), self.scale.disconnect()
         #  Disconnect Arduino
         if self.arduino and self.arduino.connection:
             self.log("Disconnecting Arduino..."); self.arduino.close(); self.log("-> Arduino Disconnected.")
         # Update UI after all tasks are done
         self.root.after(0, self.task_completed)

