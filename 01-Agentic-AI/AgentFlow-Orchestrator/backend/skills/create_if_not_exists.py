# Auto-generated skill: create_if_not_exists

def create_file_if_missing(path: str, content: str) -> None:
    """Create a file with the given content if it does not already exist.

    Args:
        path (str): The filesystem path where the file should be created.
        content (str): The text content to write into the file.
    """
    import os
    if not os.path.exists(path):
        # Ensure the directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        # File already exists – no action taken
        pass

# Example usage (can be removed in production):
# create_file_if_missing('output/example.txt', 'Hello, World!')
