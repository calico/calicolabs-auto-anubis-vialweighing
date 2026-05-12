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
from core.utils import ProcessCancelledError, coordinate_to_index, index_to_coordinate, calculate_vial_pose, sanitize_csv_value
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
        self.scanner_params = {"CSV_HEADER": ['Coordinate', 'Scanned Barcode', 'Vial Weight', 'Unit']}

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
        try:
            if self.robot and self.robot.IsConnected():
                self.robot.DeactivateRobot()
                self.robot.Disconnect()
                self.log("-> Robot deactivated and disconnected forcefully.")
        except Exception as e:
            self.log(f"Error during emergency robot disconnect: {e}")
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


    # --- Motion helper methods ---

    def _check_for_events(self):
        self.pause_event.wait()
        if self.cancel_event.is_set():
            raise ProcessCancelledError("Process cancelled by user.")

    def _smart_sleep(self, duration):
        start = time.time()
        while time.time() - start < duration:
            self._check_for_events()
            time.sleep(min(0.1, duration - (time.time() - start)))

    def _move_pose(self, pose):
        self.robot.MovePose(*pose)
        self.robot.WaitIdle()
        self._check_for_events()

    def _move_lin(self, pose):
        self.robot.MoveLin(*pose)
        self.robot.WaitIdle()
        self._check_for_events()

    def _move_joints(self, joints):
        self.robot.MoveJoints(*joints)
        self.robot.WaitIdle()
        self._check_for_events()

    def _move_gripper(self, dist, sleep_time=0.0):
        self.robot.MoveGripper(dist)
        self.robot.WaitIdle()
        self._check_for_events()
        if sleep_time > 0:
            self._smart_sleep(sleep_time)

    def _move_to_nest3_safety(self, nest_params, context=""):
        if nest_params['name'] == 'Nest 3':
            if context:
                self.log(f"   -> {context}")
            else:
                self.log("   -> Moving to Nest 3 safety position.")
            self._move_joints(nest_params["intermediate_pose_nest3_safety"])

    # --- Robot setup ---

    def _connect_and_configure_robot(self):
        robot_params = APP_CONFIG.get("robot_params", {})
        self.log("Connecting...")
        self.robot.Connect(address=self.common_params["ROBOT_IP"])
        self._check_for_events()
        self.robot.ActivateRobot()
        self._check_for_events()
        self.robot.Home()
        self._check_for_events()
        self.log("-> Robot Homed and Activated.")

        torque_limit = robot_params.get("torque_limit", 50)
        self.robot.SetTorqueLimitsCfg(4, 1)
        self.robot.SetTorqueLimits(torque_limit, torque_limit, torque_limit, torque_limit, torque_limit, torque_limit)
        self.log(f"-> Torque limits set to {torque_limit}% for all joints.")

        gripper_force = robot_params.get("gripper_force", 5)
        self.robot.SetGripperForce(gripper_force)
        self.log(f"-> Gripper force detection enabled and limited to {gripper_force}%.")

        gripper_vel = robot_params.get("gripper_vel", 10)
        self.robot.SetGripperVel(gripper_vel)
        self.log(f"-> Gripper speed limited to {gripper_vel}%")

        gripper_range = robot_params.get("gripper_range", [3, 5.8])
        self.robot.SetGripperRange(*gripper_range)
        self.log(f"-> Set the grippers range from {gripper_range[0]} to {gripper_range[1]}")

        joint_vel = robot_params.get("joint_vel", 80)
        joint_acc = robot_params.get("joint_acc", 75)
        cart_lin_vel = robot_params.get("cart_lin_vel", 400)
        self.robot.SetJointVel(joint_vel)
        self.robot.SetJointAcc(joint_acc)
        self.robot.SetCartLinVel(cart_lin_vel)

    # --- Barcode scanning ---

    def _scan_barcode_with_retry(self, nest_params, approach_pose, current_target_pose,
                                  retry_approach_pose, gripper_open, gripper_close,
                                  home_joints, scanner_pose):
        """Attempts to scan a barcode with one re-grip retry. Returns the barcode or None."""
        scanned_barcode = None
        try:
            self.log("   -> Waiting for barcode scan (Attempt 1/2)...")
            scanned_barcode = self.barcode_queue.get(timeout=4)
        except queue.Empty:
            self.log("   -> Scan timed out. Returning vial to re-grip for second attempt.")
            self._move_joints(home_joints)
            self._move_to_nest3_safety(nest_params, "(Retry) Moving to Nest 3 safety position before re-gripping.")

            self._move_pose(approach_pose)
            self._move_lin(retry_approach_pose)
            self._move_gripper(gripper_open)
            self._move_lin(current_target_pose)
            self._move_gripper(gripper_close, .2)
            self._move_lin(approach_pose)

            self._move_to_nest3_safety(nest_params, "(Retry) Moving to Nest 3 safety position before proceeding to scanner.")
            self._move_joints(home_joints)
            self._move_pose(scanner_pose)

            try:
                self.log("   -> Waiting for barcode scan (Attempt 2/2)...")
                scanned_barcode = self.barcode_queue.get(timeout=4)
            except queue.Empty:
                self.log("   -> Scan failed on second attempt.")

        return scanned_barcode

    # --- Scale interaction ---

    def _place_vial_on_scale(self, nest_params, scale_dropoff, scale_dropoff_approach, gripper_open_bal, user_name):
        robot_params = APP_CONFIG.get("robot_params", {})
        scale_vel = robot_params.get("cart_lin_vel_scale", 50)
        travel_vel = robot_params.get("cart_lin_vel", 400)

        if not self.scale.open_doors(self, user_name):
            raise ProcessCancelledError("Process ended due to door failure.")
        self._check_for_events()

        self.robot.SetCartLinVel(scale_vel)
        self._move_pose(scale_dropoff_approach)
        self.log(f"Arm started moving ... Timestamp: {datetime.now().time()}")
        self._move_lin(scale_dropoff)
        self._move_gripper(gripper_open_bal, .5)
        self._move_lin(scale_dropoff_approach)
        self._move_pose(nest_params['intermediate_pose_3'])
        self.robot.SetCartLinVel(travel_vel)

        if not self.scale.close_doors(self, user_name):
            raise ProcessCancelledError("User chose to end the process due to door failure.")
        self._check_for_events()
        self.log("Waiting 3 seconds for air currents and vibrations to settle...")
        self._smart_sleep(3)

    def _pick_vial_from_scale(self, nest_params, scale_pickup, scale_pickup_approach, gripper_close_bal, user_name):
        robot_params = APP_CONFIG.get("robot_params", {})
        scale_vel = robot_params.get("cart_lin_vel_scale", 50)
        travel_vel = robot_params.get("cart_lin_vel", 400)

        if not self.scale.open_doors(self, user_name):
            raise ProcessCancelledError("User chose to end the process due to door failure.")
        self._check_for_events()

        self.robot.SetCartLinVel(scale_vel)
        self._move_pose(scale_pickup_approach)
        self._move_lin(scale_pickup)
        self._move_gripper(gripper_close_bal, .5)
        self._move_lin(scale_pickup_approach)
        self._move_pose(nest_params['intermediate_pose_3'])
        self.robot.SetCartLinVel(travel_vel)

    def _weigh_vial_with_recovery(self, nest_params, scale_dropoff, scale_dropoff_approach,
                                   scale_pickup, scale_pickup_approach,
                                   gripper_open_bal, gripper_close_bal, user_name):
        """Gets a stable weight, running a recovery loop if the first attempt fails.
        Returns (weight, unit)."""
        stable_weight, stable_unit = self.scale.get_stable_weight()
        self._check_for_events()

        if stable_weight is not None:
            return stable_weight, stable_unit

        log_message = "Initial weight measurement failed. Starting recovery process."
        self.log(log_message)
        self.root.after(0, self.send_gchat_notification, log_message, user_name)

        while True:
            self.log("   -> Picking up vial to reset scale...")
            self._pick_vial_from_scale(nest_params, scale_pickup, scale_pickup_approach, gripper_close_bal, user_name)

            if not self.scale.close_doors(self, user_name):
                raise ProcessCancelledError("User chose to end the process due to door failure.")
            self._check_for_events()
            self._smart_sleep(1)

            self.log("   -> Resetting the scale...")
            self.scale.power_on_or_reset()
            self._check_for_events()
            self.scale.tare()
            self._check_for_events()

            self.log("   -> Placing vial back on the scale...")
            self._place_vial_on_scale(nest_params, scale_dropoff, scale_dropoff_approach, gripper_open_bal, user_name)

            self.log("   -> Retrying to get stable weight after reset...")
            stable_weight, stable_unit = self.scale.get_stable_weight()
            self._check_for_events()

            if stable_weight is not None:
                log_message = "Stable weight obtained. Reset successful"
                self.log(log_message)
                self.root.after(0, self.send_gchat_notification, log_message, user_name)
                return stable_weight, stable_unit

            self.log("  <- Failed to get stable weight after recovery. Prompting user...")
            notification_message = "Weighing failed after recovery. Process is paused pending user input."
            self.root.after(0, self.send_gchat_notification, notification_message, user_name)
            should_retry = self.safe_askretrycancel(
                "Weighing Failed",
                "Could not get a stable weight after resetting the scale.\n\nDo you want to retry the entire recovery process?"
            )
            if should_retry:
                self.log("-> User chose to RETRY the recovery process.")
            else:
                cancel_message = "User cancelled the process after failed weight measurement."
                self.log(f"!!! {cancel_message}")
                self.root.after(0, self.send_gchat_notification, cancel_message, user_name)
                raise ProcessCancelledError(cancel_message)

    # --- Concurrent tare ---

    def _concurrent_tare(self, cancel_evt, user_name):
        try:
            if cancel_evt.is_set():
                return
            if not self.scale.close_doors(self, user_name):
                self.log("ERROR: Door failure during concurrent tare.")
                return

            self.log("Waiting for air currents and vibrations to settle before taring...")
            for _ in range(30):
                if cancel_evt.is_set():
                    return
                time.sleep(0.1)

            if cancel_evt.is_set():
                return
            stable_weight, _ = self.scale.get_stable_weight()
            if stable_weight is None:
                self.log("Warning: Could not get stable weight prior to tare. Proceeding anyway.")

            if cancel_evt.is_set():
                return
            if not self.scale.tare():
                self.log("Warning: Tare operation failed. Proceeding, but weight may be inaccurate.")
            for _ in range(10):
                if cancel_evt.is_set():
                    return
                time.sleep(0.1)
        except Exception as e:
            self.log(f"Concurrent tare error: {e}")

    # --- Cancel recovery ---

    def _safe_cancel_recovery(self, gripper_open_dist):
        if not (self.robot and self.robot.IsConnected()):
            return
        try:
            self.robot.WaitIdle()
            self.log("Opening gripper...")
            self.robot.MoveGripper(gripper_open_dist)
            self.robot.WaitIdle()

            self.log("Retracting linearly upwards to clear obstacles...")
            try:
                current_pose = self.robot.GetPose()
                if current_pose:
                    safe_z_pose = list(current_pose)
                    safe_z_pose[2] += 50.0
                    self.robot.MoveLin(*safe_z_pose)
                    self.robot.WaitIdle()
            except mdr.MecademicException as e_pose:
                self.log(f"Warning: Could not perform linear retraction: {e_pose}")

            self.log("Moving to final home position...")
            self.robot.MoveJoints(*self.common_params["home_position_joints"])
            self.robot.WaitIdle()
            self.log("-> Robot returned to home position safely.")
        except mdr.MecademicException as move_err:
            self.log(f"Could not perform safe return after cancel: {move_err}")

    # --- Disconnect helpers ---

    def _disconnect_all(self, user_name):
        try:
            if self.robot and self.robot.IsConnected():
                self.log("Disconnecting robot...")
                self.robot.DeactivateRobot()
                self.robot.Disconnect()
                self.log("-> Disconnected.")
        except Exception as e:
            self.log(f"Error during robot disconnect: {e}")
        try:
            if self.scale and self.scale.connection:
                self.log("Disconnecting Scale...")
                self.scale.close_doors(self, user_name)
                self.scale.disconnect()
        except Exception as e:
            self.log(f"Error during scale disconnect: {e}")
        try:
            if self.arduino and self.arduino.connection:
                self.log("Disconnecting Arduino...")
                self.arduino.close()
                self.log("-> Arduino Disconnected.")
        except Exception as e:
            self.log(f"Error during Arduino disconnect: {e}")

    # --- Main orchestrator ---

    def robot_task(self, tasks, user_name):
        self.cycle_count = 0
        self.robot = mdr.Robot()
        self.arduino = ArduinoController(port=self.common_params["ARDUINO_PORT"], baudrate=115200, log_callback=self.log)
        self.scale = MettlerToledoController(port=self.common_params["SCALE_PORT"], log_callback=self.log, arduino_controller=self.arduino, app_instance=self)
        csv_filepath = None
        tare_thread = None
        gripper_open_nest = APP_CONFIG.get("robot_params", {}).get("gripper_range", [3, 5.8])[0]

        try:
            self._connect_and_configure_robot()

            self.log("Connecting to and initializing the scale...")
            if not self.scale.connect():
                raise ConnectionError("Failed to connect to the Mettler Toledo scale.")
            self._check_for_events()

            self.scale.power_on_or_reset()
            self._check_for_events()
            self.log("-> Scale Initialized and Zeroed.")

            for nest_params in tasks:
                self.log(f"\n********** STARTING {nest_params['name']} with {nest_params['rack_name']} **********")
                self._check_for_events()

                if nest_params['name'] == 'Nest 3':
                    self.log("   -> Moving to Nest 3 safety position to begin task.")
                    self._move_joints(nest_params["intermediate_pose_nest3_safety"])

                GRIPPER_OPEN_NEST = nest_params.get('gripper_open_dist', 3.5)
                GRIPPER_CLOSED_NEST = nest_params.get('gripper_close_dist', 1.25)
                GRIPPER_OPEN_BAL = nest_params.get('gripper_open_dist_bal', 5.8)
                GRIPPER_CLOSED_BAL = nest_params.get('gripper_close_dist_bal', 0.75)
                LIFT_UP_MM = nest_params.get('lift_up_mm', 50.0)
                RESET_INTERVAL = nest_params.get('row_reset_interval', 8)
                scale_dropoff = nest_params.get("scale_dropoff", [-0.768729, 262.21615, 130, -90, -0.16875, 90])
                scale_pickup = nest_params.get("scale_pickup", [-0.768729, 262.21615, 127, -90, -0.16875, 90])
                MAX_WELLS = nest_params.get('max_wells', 96)
                RETRY_APPROACH_MM = nest_params.get('retry_approach_mm', 10)
                RACK_NAME = nest_params.get('file_label')
                base_pose = nest_params['base_pose']
                home_position_joints = nest_params['home_position_joints']
                gripper_open_nest = GRIPPER_OPEN_NEST

                dynamic_scanner_pose = list(nest_params['scanner_pose'])
                if 'scanner_z_position' in nest_params:
                    dynamic_scanner_pose[2] = nest_params['scanner_z_position']
                    self.log(f"   -> Using custom scanner Z-position: {dynamic_scanner_pose[2]}")

                self._move_gripper(GRIPPER_OPEN_BAL, 1.5)
                self._move_gripper(GRIPPER_OPEN_NEST, 1.5)

                file_path = nest_params["CSV_FILE_PATH"]
                rack_barcode = nest_params["rack_barcode"]
                timestamp_str = datetime.now().strftime("%Y.%m.%d_%H.%M")
                csv_filepath = os.path.join(file_path, f"{RACK_NAME}_{rack_barcode}_{timestamp_str}.csv")
                os.makedirs(file_path, exist_ok=True)

                with open(csv_filepath, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    if os.path.getsize(csv_filepath) == 0:
                        writer.writerow(self.scanner_params["CSV_HEADER"])

                    start_index, end_index = nest_params["start_index"], nest_params["end_index"]
                    last_completed_pose = None
                    scale_dropoff_approach = list(scale_dropoff); scale_dropoff_approach[2] = 200
                    scale_pickup_approach = list(scale_pickup); scale_pickup_approach[2] = 200

                    for i in range(start_index, end_index + 1):
                        vial_coord = index_to_coordinate(i, MAX_WELLS, RESET_INTERVAL)
                        self.log(f"--- CYCLE for Vial {vial_coord} ({nest_params['name']}) ---")
                        self._check_for_events()

                        current_target_pose = calculate_vial_pose(base_pose, nest_params['name'], i, nest_params, RESET_INTERVAL)
                        approach_pose = list(current_target_pose); approach_pose[2] += LIFT_UP_MM
                        retry_approach_pose = list(current_target_pose); retry_approach_pose[2] += RETRY_APPROACH_MM

                        # Lift off from previous vial position
                        if last_completed_pose is not None:
                            lift_off_pose = list(last_completed_pose); lift_off_pose[2] += LIFT_UP_MM
                            self._move_lin(lift_off_pose)

                        # Pick up vial from rack
                        self._move_pose(approach_pose)
                        self._move_lin(current_target_pose)
                        self._move_gripper(GRIPPER_CLOSED_NEST)
                        self._move_lin(approach_pose)

                        # Navigate to scanner
                        self._move_to_nest3_safety(nest_params, "Moving to Nest 3 safety position before proceeding.")
                        self._move_joints(home_position_joints)
                        self._move_pose(dynamic_scanner_pose)

                        # Scan barcode (with retry)
                        scanned_barcode = self._scan_barcode_with_retry(
                            nest_params, approach_pose, current_target_pose, retry_approach_pose,
                            GRIPPER_OPEN_NEST, GRIPPER_CLOSED_NEST, home_position_joints, dynamic_scanner_pose
                        )

                        if scanned_barcode is None:
                            # Both scan attempts failed — return vial and skip
                            self.log("   -> Scan failed on second attempt. Returning vial and skipping.")
                            self._move_joints(home_position_joints)
                            self._move_to_nest3_safety(nest_params, "(Failed Scan) Moving to Nest 3 safety position before returning vial.")
                            self._move_pose(approach_pose)
                            self._move_lin(retry_approach_pose)
                            self._move_gripper(GRIPPER_OPEN_NEST)

                            writer.writerow([vial_coord, "Vial Not Found"])
                            csvfile.flush()
                            self.root.after(0, self.send_gchat_notification, f"Vial not found at {nest_params['name']} - {vial_coord}", user_name)
                            last_completed_pose = current_target_pose
                            continue

                        # Valid scan — proceed with weighing cycle
                        self.cycle_count += 1
                        self.log(f"--- Starting Cycle #{self.cycle_count} ---")

                        # Wait for any concurrent tare from the previous cycle
                        if tare_thread is not None and tare_thread.is_alive():
                            self.log("Waiting for scale to finish concurrent tare from previous cycle...")
                            while tare_thread.is_alive():
                                self._check_for_events()
                                time.sleep(0.1)

                        # Periodic scale adjustment check
                        if self.cycle_count == 1 or self.cycle_count % 10 == 0:
                            self.log(f"Cycle {self.cycle_count} is a multiple of 10. Performing scale adjustment check.")
                            if not self.scale.scale_adjustment_check(self, user_name):
                                popup_message = "Manual scale adjustment required.\n\nPress OK when completed, or Cancel to stop the process."
                                self.log(popup_message)
                                self.root.after(0, self.send_gchat_notification, "Manual scale adjustment required. Process is paused.", user_name)
                                user_choice = self.safe_askokcancel("Manual Adjustment Required", popup_message)
                                if not user_choice:
                                    cancel_message = "Process cancelled by user during manual scale adjustment."
                                    self.log(cancel_message)
                                    self.root.after(0, self.send_gchat_notification, cancel_message, user_name)
                                    raise ProcessCancelledError(cancel_message)
                        self.log("Scale adjustment check complete. Resuming operations.")
                        self._check_for_events()

                        # One-time initial tare before the first vial
                        if self.cycle_count == 1:
                            self.log("Closing doors to prepare for one-time initial tare...")
                            if not self.scale.close_doors(self, user_name):
                                raise ProcessCancelledError("process ended due to door failure.")
                            self.log("Waiting for air currents and vibrations to settle before initial taring...")
                            self._check_for_events()
                            self._smart_sleep(3)
                            stable_weight, _ = self.scale.get_stable_weight()
                            if stable_weight is None:
                                self.log("Warning: Could not get stable weight prior to initial tare. Proceeding anyway.")
                            if not self.scale.tare():
                                self.log("Warning: Initial tare operation failed. Proceeding, but weight may be inaccurate.")
                            self._check_for_events()
                            self._smart_sleep(1)

                        scanned_barcode = sanitize_csv_value(scanned_barcode)
                        self.log(f"   -> Scan received: {scanned_barcode} for vial {vial_coord}. Resuming...")

                        # Move to scale area
                        self._move_pose(nest_params['intermediate_pose_2'])
                        self._move_pose(nest_params['intermediate_pose_3'])

                        # Place vial on scale and weigh
                        self._place_vial_on_scale(nest_params, scale_dropoff, scale_dropoff_approach, GRIPPER_OPEN_BAL, user_name)
                        stable_weight, stable_unit = self._weigh_vial_with_recovery(
                            nest_params, scale_dropoff, scale_dropoff_approach,
                            scale_pickup, scale_pickup_approach,
                            GRIPPER_OPEN_BAL, GRIPPER_CLOSED_BAL, user_name
                        )

                        # Write data to CSV
                        writer.writerow([
                            vial_coord, scanned_barcode,
                            f"{stable_weight:.5f}" if stable_weight is not None else "N/A",
                            stable_unit or "N/A"
                        ])
                        csvfile.flush()

                        # Pick vial up from scale
                        self._pick_vial_from_scale(nest_params, scale_pickup, scale_pickup_approach, GRIPPER_CLOSED_BAL, user_name)

                        # Start concurrent tare for the next vial
                        if i < end_index:
                            self.log("Starting background thread to close doors and tare scale for the next vial...")
                            tare_thread = threading.Thread(target=self._concurrent_tare, args=(self.cancel_event, user_name), daemon=True)
                            tare_thread.start()

                        # Return vial to rack
                        self._move_pose(nest_params['intermediate_pose_2'])
                        self._move_joints(home_position_joints)
                        self._move_to_nest3_safety(nest_params, "Moving to Nest 3 safety position before returning vial from scale.")
                        self._move_pose(approach_pose)
                        self.robot.SetCartLinVel(APP_CONFIG.get("robot_params", {}).get("cart_lin_vel", 400))
                        self._move_lin(current_target_pose)
                        self._move_gripper(GRIPPER_OPEN_NEST)

                        last_completed_pose = self.robot.GetPose()
                        self.log("   -> Cycle complete.\n")
                        self._smart_sleep(.5)

                    if last_completed_pose is not None:
                        self.log(f"-> Finished rack {nest_params['name']}. Lifting up before next task.")
                        lift_off_pose = list(last_completed_pose); lift_off_pose[2] += LIFT_UP_MM
                        self._move_lin(lift_off_pose)

            self.log("***** All selected tasks are complete. *****")
            self.robot.MoveJoints(*self.common_params['home_position_joints'])
            self.robot.WaitIdle()
            self.log("-> Robot is at final home position.")
            log_filepath = self.save_log_to_file()
            self.scale.close_doors(self, user_name)
            self.root.after(0, self.send_gchat_notification, "Process completed successfully", user_name, csv_filepath, log_filepath)

        except ProcessCancelledError as e:
            self.log(str(e))
            self.log("Aborting process...")
            log_filepath = self.save_log_to_file("cancelled_process")
            self.root.after(0, self.send_gchat_notification, "Process was cancelled by the user", user_name, csv_filepath, log_filepath)
            self._safe_cancel_recovery(gripper_open_nest)

        except Exception as e:
            error_message = f"Robot has errored due crash or incorrect labware definitions. User involvement necessary: {e}"
            self.log(f"\n!!!!!!!! AN ERROR OCCURRED/ ARM HAS CRASHED !!!!!!!!\n{e}\n")
            log_filepath = self.save_log_to_file("incomplete_log")
            self.root.after(0, self.send_gchat_notification, f"ROBOT ERROR: {error_message}", user_name, csv_filepath, log_filepath)
            self.root.after(0, self.show_error_popup)

        finally:
            self._disconnect_all(user_name)
            self.root.after(0, self.task_completed)

