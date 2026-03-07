from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def make_icon(source: Path, output_dir: Path) -> tuple[Path, Path]:
    image = Image.open(source).convert("RGBA")
    pixels = image.getdata()
    converted = []
    for r, g, b, a in pixels:
        if a > 0 and r <= 20 and g <= 20 and b <= 20:
            converted.append((r, g, b, 0))
        else:
            converted.append((r, g, b, a))
    image.putdata(converted)
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / "app_icon.png"
    ico_path = output_dir / "app_icon.ico"
    image.save(png_path, format="PNG")
    image.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return png_path, ico_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("logo.png"))
    parser.add_argument("--output", type=Path, default=Path("build"))
    args = parser.parse_args()
    png_path, ico_path = make_icon(args.source, args.output)
    print(f"icon-png={png_path}")
    print(f"icon-ico={ico_path}")


if __name__ == "__main__":
    main()
