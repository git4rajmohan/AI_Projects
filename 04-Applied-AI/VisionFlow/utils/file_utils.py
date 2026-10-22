import re
from pathlib import Path

INPUT_DIR = Path("data/input")


def save_upload(name: str, data: bytes, dest_dir: Path = INPUT_DIR) -> Path:
    # Retention: same-named uploads overwrite; data/input and data/output are git-ignored and cleared manually.
    # Path(name).name strips directories (no traversal); the regex drops odd characters.
    stem = re.sub(r"[^\w.\- ]", "_", Path(name).name).strip(". ") or "upload"
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / stem
    path.write_bytes(data)
    return path


def output_path(input_path: str | Path, output_dir: str | Path = "data/output") -> Path:
    return Path(output_dir) / f"{Path(input_path).stem}_annotated.mp4"
