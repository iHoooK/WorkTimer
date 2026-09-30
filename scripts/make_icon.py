"""Generate the shared clock brand, without downloaded assets."""

from pathlib import Path

from PIL import Image, ImageDraw


def create_icon():
    root = Path(__file__).resolve().parents[1] / "web" / "assets"
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 240, 240), fill="#22c7ff")
    draw.ellipse((40, 40, 216, 216), fill="#07111c")
    draw.line(((128, 68), (128, 128), (172, 156)), fill="#eaf2f8", width=20)
    image.save(root / "worktimer.png")
    image.save(root / "worktimer.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    create_icon()
