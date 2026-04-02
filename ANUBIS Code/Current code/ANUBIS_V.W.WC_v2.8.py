# Vial Weighing Work Cell
# By Perry Azougi {2025 Summer Intern--- Don't Forget Me :)}

import sys
import os

# Add the current directory to path so it can import the packages
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ui.app import RobotUiApp, show_splash
import customtkinter

if __name__ == "__main__":
    # --- Set customtkinter appearance and theme ---
    customtkinter.set_appearance_mode("Dark")
    customtkinter.set_default_color_theme("green")

    # 1. Create the main application window
    root = customtkinter.CTk()

    # 2. Define the path to your splash image and the duration
    SPLASH_IMAGE_PATH = r"C:\Users\balance\Documents\MECA500 Code\Code\Completed Software\Anubis.png"
    SPLASH_DURATION_MS = 3500 # 3.5 seconds

    # 3. Call the splash screen function.
    show_splash(root, SPLASH_IMAGE_PATH, SPLASH_DURATION_MS)

    # 4. Create the instance of your main application class.
    app = RobotUiApp(root)

    # 5. Start the Tkinter event loop.
    root.mainloop()
