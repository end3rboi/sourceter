"""Generate the app icon (icon.png + icon.ico). Run once: python make_icon.py

A rename glyph: a photo, and over it the text field with a caret that every
"rename" icon uses.
"""

from PIL import Image, ImageDraw

SIZE = 1024
BG = (16, 18, 22)
CARD = (43, 49, 60)
CARD_EDGE = (74, 83, 100)
SKY = (58, 67, 84)
HILL = (96, 108, 130)
SUN = (150, 161, 182)
ACCENT = (79, 124, 255)
LIGHT = (231, 233, 238)


def main():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # tile
    d.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=224, fill=BG)

    # the photo behind
    photo = (168, 150, 856, 660)
    d.rounded_rectangle(photo, radius=44, fill=CARD, outline=CARD_EDGE, width=8)

    # a picture inside it: sun and two hills, clipped to the photo
    inner = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    di = ImageDraw.Draw(inner)
    di.rectangle((photo[0] + 8, photo[1] + 8, photo[2] - 8, photo[3] - 8), fill=SKY)
    di.ellipse((300, 240, 400, 340), fill=SUN)
    di.polygon([(200, 640), (430, 380), (620, 640)], fill=HILL)
    di.polygon([(480, 640), (660, 430), (840, 640)], fill=(74, 84, 104))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (photo[0] + 8, photo[1] + 8, photo[2] - 8, photo[3] - 8), radius=38, fill=255)
    img.paste(inner, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # the rename field, overlapping the photo's lower edge
    field = (120, 590, 904, 830)
    d.rounded_rectangle((field[0] - 14, field[1] - 14, field[2] + 14, field[3] + 14),
                        radius=60, fill=BG)                     # cut-out halo
    d.rounded_rectangle(field, radius=46, fill=(26, 30, 37), outline=ACCENT, width=10)

    # text bars, then the caret sitting after them
    y0, y1 = 686, 734
    x = 190
    for width in (150, 110, 190):
        d.rounded_rectangle((x, y0, x + width, y1), radius=24, fill=LIGHT)
        x += width + 34
    d.rounded_rectangle((x + 6, 664, x + 30, 756), radius=12, fill=ACCENT)   # caret
    d.rounded_rectangle((x - 18, 654, x + 54, 674), radius=10, fill=ACCENT)  # serifs
    d.rounded_rectangle((x - 18, 746, x + 54, 766), radius=10, fill=ACCENT)

    img.save("icon.png")
    img.save("icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote icon.png and icon.ico")


if __name__ == "__main__":
    main()
