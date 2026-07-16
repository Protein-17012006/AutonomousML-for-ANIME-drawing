import numpy as np
from PIL import Image

from benchmark.largegap.montage import strip


def test_strip_writes_grid(tmp_path):
    frames = [np.full((48, 64, 3), value, np.uint8)
              for value in range(0, 250, 50)]
    out = tmp_path / "m.jpg"
    strip(
        {"gt": frames, "rife": frames, "ldf_ft": frames},
        col_idx=[0, 2, 4],
        out_jpg=out,
    )
    with Image.open(out) as image:
        width, height = image.size
    assert width > 3 * 60 and height > 3 * 48


def test_gt_row_is_first(tmp_path):
    dark = [np.zeros((20, 30, 3), np.uint8)]
    bright = [np.full((20, 30, 3), 255, np.uint8)]
    out = tmp_path / "ordered.jpg"
    strip({"rife": dark, "gt": bright}, [0], out, label_h=18)
    with Image.open(out) as image:
        pixels = np.asarray(image)
    assert pixels[20:38].mean() > pixels[58:76].mean()
