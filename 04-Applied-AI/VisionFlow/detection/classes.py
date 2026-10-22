DEFAULT_CLASSES = ("person", "car", "bus", "truck", "motorcycle", "bicycle")


def supported_classes(model_names: dict[int, str]) -> list[str]:
    """Default target classes that the loaded model can actually detect."""
    available = set(model_names.values())
    return [c for c in DEFAULT_CLASSES if c in available]
