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


def calculate_vial_pose(base_pose, nest_name, index, increments, reset_interval):
    """Calculates the target pose for a vial based on its index and nest location.

    Args:
        base_pose: The [x, y, z, a, b, c] base pose for the nest's A1 position.
        nest_name: One of 'Nest 1', 'Nest 2', 'Nest 3'.
        index: Zero-based vial index.
        increments: Dict with keys like 'increment_1x_mm', 'increment_1y_mm', etc.
        reset_interval: Number of vials per column (row_reset_interval from config).

    Returns:
        A new list representing the target pose.
    """
    group_number, step_in_group = divmod(index, reset_interval)
    target_pose = list(base_pose)

    if nest_name == 'Nest 1':
        x_offset = step_in_group * increments.get('increment_1x_mm', -9.0)
        y_offset = group_number * increments.get('increment_1y_mm', 9.0)
        target_pose[0] += x_offset
        target_pose[1] -= y_offset
    elif nest_name == 'Nest 2':
        y_offset = step_in_group * increments.get('increment_2y_mm', 9.0)
        x_offset = group_number * increments.get('increment_2x_mm', -9.0)
        target_pose[1] += y_offset
        target_pose[0] += x_offset
    elif nest_name == 'Nest 3':
        x_offset = step_in_group * increments.get('increment_3x_mm', -9.0)
        y_offset = group_number * increments.get('increment_3y_mm', 9.0)
        target_pose[0] -= x_offset
        target_pose[1] += y_offset

    return target_pose


def sanitize_csv_value(value):
    """Escapes values that could trigger formula injection when opened in spreadsheet software."""
    if isinstance(value, str) and value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value
