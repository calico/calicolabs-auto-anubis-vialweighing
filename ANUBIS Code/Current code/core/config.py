import os
import json

CONFIG_FILE_NAME = "config.json"

def load_config():
    """Loads configuration from config.json. Returns defaults if missing or invalid."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, CONFIG_FILE_NAME)
    
    # Default configuration
    config = {
        "hardware": {
            "robot_ip": "192.168.0.100",
            "scale_port": "COM3",
            "scale_baudrate": 9600,
            "arduino_port": "COM4"
        },
        "paths": {
            "rack_library": "Rack Library",
            "log_files": "Log_Files",
            "csv_files": "Rack_CSV_Files",
            "splash_image": "Anubis.png"
        },
        "notifications": {
            "gchat_webhook_url": ""
        }
    }
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                
                # Deep update for nested dictionaries
                for key, val in user_config.items():
                    if isinstance(val, dict) and key in config:
                        config[key].update(val)
                    else:
                        config[key] = val
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to parse config.json. Using default settings. Error: {e}")
    else:
        print(f"Warning: config.json not found at {config_path}. Using default settings.")
        
    # Resolve relative paths to absolute paths based on the script's directory
    for path_key, path_value in config["paths"].items():
        if not os.path.isabs(path_value):
            config["paths"][path_key] = os.path.join(base_dir, path_value)
            
    return config

# Global config instance
APP_CONFIG = load_config()
