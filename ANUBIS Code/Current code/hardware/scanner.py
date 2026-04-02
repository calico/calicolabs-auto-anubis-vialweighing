import keyboard

class BarcodeScannerListener:
    """
    Listens for and suppresses keyboard input from a barcode scanner, 
    preventing it from typing into other applications.
    """
    def __init__(self, output_queue): # creates a new instance
        self.output_queue = output_queue # Stores object that will be used to pass barcodes to the main program
        self.barcode_buffer = [] # creates empty list for scanned barcode
        self.hook = None # variable that holds unique ID for active keyboard hook (keyboard hook intercepts keystrokes --
                         # -- so scanner doesnt type into other apps while code is runner -- disables regular keyboard while running also.)

    def on_key_event(self, event):
        if event.event_type == keyboard.KEY_DOWN: # Checks if the event is a key being pressed down (not released)
            if event.name == 'enter': # Checks if the pressed key is 'enter', which signals the end of a scan
                if self.barcode_buffer: # Proceeds only if the buffer contains characters
                    scanned_string = "".join(self.barcode_buffer) # Joins the list of characters in the buffer into a single string
                    self.output_queue.put(scanned_string) # Adds the complete barcode string to the output queue for processing
                    self.barcode_buffer = [] # Resets the buffer to an empty list for the next scan
            elif len(event.name) == 1:# If the key is not 'enter', check if it is a single character (e.g., 'A', '7')
                self.barcode_buffer.append(event.name) # Appends the character to the buffer

    def start_listening(self): # A method to start capturing keyboard events
        self.hook = keyboard.hook(self.on_key_event, suppress=True) # Registers the 'on_key_event' method to handle all keyboard events and suppresses them
        print("Listener started. Scanner input is now captured exclusively.") 

    def stop(self): # A method to stop capturing keyboard events
        if self.hook: # Checks if the listener hook is currently active
            keyboard.unhook(self.hook) # Removes the keyboard hook, returning keyboard control to the OS
            self.hook = None # Resets the hook attribute to None
            print("Listener stopped. Keyboard input is back to normal.")
