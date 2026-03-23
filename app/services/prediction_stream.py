def parse_raw_frames(raw_text: str) -> list[list[float]]:
    """
    Parse raw ESP32 data block into a list of 22-float frames.

    Strips 'S' and 'E' markers, keeps only lines with exactly 22 numeric values.
    Works for both serial and REST API input.
    """
    frames = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [x for x in line.split() if x not in ["S", "E"]]
        if len(parts) == 22:
            try:
                frames.append([float(x) for x in parts])
            except ValueError:
                continue
    return frames
