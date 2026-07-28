"""One-off, dev-time script: generates dashboard/assets/plane_icon.png --
a simple plane glyph pointing "up" (north/0deg), since pydeck's IconLayer
rotates it per-aircraft via getAngle from true_track. Run once; the PNG is
committed, no runtime fetch needed.
"""
from PIL import Image, ImageDraw

SIZE = 128
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

c = SIZE / 2
color = (255, 255, 255, 255)

# A simple arrow/plane silhouette pointing up (north), matching the
# convention pydeck's getAngle rotates clockwise from.
draw.polygon(
    [
        (c, c - 52),  # nose
        (c + 10, c - 8),
        (c + 46, c + 18),
        (c + 10, c + 6),
        (c + 14, c + 46),
        (c, c + 34),
        (c - 14, c + 46),
        (c - 10, c + 6),
        (c - 46, c + 18),
        (c - 10, c - 8),
    ],
    fill=color,
)

img.save("dashboard/assets/plane_icon.png")
print("wrote dashboard/assets/plane_icon.png")
