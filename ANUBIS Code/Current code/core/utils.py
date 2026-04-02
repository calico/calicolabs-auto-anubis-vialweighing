import re

class ProcessCancelledError(Exception):
    """Custom exception for handling user-initiated cancellation."""
    pass

def coordinate_to_index(coord, max_wells=96, reset_interval=8):
    """Converts alphanumeric coordinate (e.g., 'A1', 'H12') to a zero-based index."""
    """These values are placeholders as they are later defined by a json file, if nothing is provided then these values are default."""
    if not isinstance(coord, str): return -1
    coord = coord.upper().strip()
    
    # Generate valid column letters based on the reset_interval
    col_letters = [chr(ord('A') + i) for i in range(reset_interval)]
    valid_cols_str = "".join(col_letters)
    
    # Make the regex dynamic based on the valid columns
    match = re.match(fr'^([{valid_cols_str}])(1[0-9]{{0,1}}|[1-9])$', coord)
    if not match:
        return -1
    
    col_letter, row_number_str = match.groups()
    
    col_index = ord(col_letter) - ord('A')
    row_index = int(row_number_str) - 1
    
    num_rows = max_wells // reset_interval
    if not (0 <= row_index < num_rows):
        return -1

    return row_index * reset_interval + col_index

def index_to_coordinate(index, max_wells=96, reset_interval=8):
    """Converts a zero-based index to an alphanumeric coordinate."""
    if not (0 <= index < max_wells):
        return "N/A"
    
    row_index = index // reset_interval
    col_index = index % reset_interval
    
    col_letter = chr(ord('A') + col_index)
    row_number = row_index + 1
    
    return f"{col_letter}{row_number}"
