"""Digi's room, v2: real per-tile tones, a clean glassy window, glowing string lights,
and shading on the little things (ball, camera, pot, plant, books) so they pop."""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

src, dst = sys.argv[1], sys.argv[2]
img = np.array(Image.open(src).convert("RGB")).astype(np.float32) / 255.0
H, W, _ = img.shape
rng = np.random.default_rng(7)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
lines = (img.max(-1) < 0.12)


def near(col, tol=0.075):
    c = np.array(col, np.float32) / 255.0
    d = np.sqrt(((img - c) ** 2).sum(-1))
    return np.clip(1 - (d - tol * 0.4) / (tol * 0.6), 0, 1)


def noise(scale, sigma=None, seed=0):
    r = np.random.default_rng(seed)
    small = r.standard_normal((H // scale + 2, W // scale + 2)).astype(np.float32)
    big = ndi.zoom(small, scale, order=3)[:H, :W]
    if sigma:
        big = ndi.gaussian_filter(big, sigma)
    return big / (big.std() + 1e-6)


def blur(m, s):
    return ndi.gaussian_filter(m.astype(np.float32), s)


def box(x0, y0, x1, y1):
    m = np.zeros((H, W), np.float32)
    m[y0:y1, x0:x1] = 1
    return m


wall = near((225, 236, 220))
floor = near((122, 85, 44), 0.06) * (yy > 1150)       # the window frame is the same brown: only the floor gets planks
rug = near((229, 216, 224), 0.05)
case = near((115, 137, 173), 0.05) * (xx > 1150)
wood = np.maximum.reduce([near((119, 91, 50), 0.05), near((74, 58, 37), 0.05),
                          near((122, 85, 44), 0.05)]) * (yy < 1150)

# window insides: sky, clouds and sun (everything inside the frame that isn't line or wood)
win_box = box(105, 235, 640, 625)
sky = near((115, 137, 173), 0.05) * win_box
arch = ((((xx - 372) / 262) ** 2 + ((yy - 622) / 380) ** 2) < 1) & (yy < 616)
inside = arch & ~lines & (wood < 0.5) & (wall < 0.3)
inside_f = inside.astype(np.float32)

# phone screen stays pure white
screen = np.zeros((H, W), np.float32)
screen[110:1395, 1230:1880] = 1
screen *= (img.min(-1) > 0.97)
screen = ndi.binary_fill_holes(ndi.binary_opening(screen > 0.5, iterations=3)).astype(np.float32)
screen = ndi.binary_dilation(screen > 0.5, iterations=6).astype(np.float32)

shade = np.ones((H, W), np.float32)
add = np.zeros((H, W, 3), np.float32)

# ---- wall tiles: each real tile (between the white grout lines) gets its own tone
tiles, n = ndi.label(wall > 0.5)
tone = rng.uniform(-1, 1, n + 1).astype(np.float32)
tone[0] = 0
tile_tone = tone[tiles]
tile_tone = np.where(wall > 0.5, tile_tone, ndi.grey_dilation(tile_tone, size=5))
grain = noise(3, 0.9, 1) * 0.5 + noise(28, 5, 2) * 0.5
shade -= wall * (0.022 * tile_tone + 0.012 * grain)
# soft bevel on tile edges: a hint of shade just under/left of the grout
grout = (img.min(-1) > 0.97) & (yy < 1150) & (screen < 0.5) & ~inside
gsh = ndi.shift(blur(grout, 2.5), (3, 3), order=1)
shade -= wall * 0.10 * np.clip(gsh, 0, 1)
# window light on the wall
d = np.sqrt(((xx - 380) / 1.15) ** 2 + (yy - 430) ** 2)
glow = np.exp(-(d / 720) ** 2)
add += (wall + rug * 0.6 + floor * 0.5)[..., None] * glow[..., None] * np.array([0.05, 0.045, 0.02], np.float32)
shade -= wall * (0.06 * np.clip(1 - yy / 260, 0, 1) ** 2)
shade -= wall * 0.05 * np.exp(-((yy - 1150) / 70) ** 2)

# ---- floor planks
plank_h = 58
row = ((yy - 1205) // plank_h).astype(int)
offs = (row * 337) % 900
seam = (((xx + offs) % 900) < 4) | (((yy - 1205) % plank_h) < 3)
plank_tone = ndi.zoom(rng.uniform(-1, 1, (H // plank_h + 2, 4)).astype(np.float32),
                      (plank_h, W / 4 + 1), order=0)[:H, :W]
wgrain = np.sin(xx / 9 + noise(16, 3, 3) * 2.5 + row * 1.7) * 0.5 + noise(2, 0.6, 4) * 0.4
shade -= floor * (0.06 * plank_tone + 0.05 * wgrain + 0.22 * seam)
shade -= floor * 0.08 * np.clip((xx - 600) / 1400, 0, 1)

# ---- rug
weave = (np.sin(xx * 1.3) * np.sin(yy * 1.3)) * 0.5 + noise(2, 0.5, 5) * 0.5
shade -= rug * (0.03 * weave + 0.006 * noise(30, 6, 6))

# ---- wood (shelves, window frame): smooth, clean grain + a lit top edge
shade -= wood * (0.03 * np.sin(xx / 7 + noise(24, 4, 7) * 2.5))
top_edge = wood * (ndi.shift((wood < 0.5).astype(np.float32), (6, 0), order=0) > 0.5)
add += top_edge[..., None] * 0.07

# ---- the window: clean sky gradient, soft sun glow, glass shine streaks
sky_grad = np.clip((yy - 250) / 380, 0, 1)
add += (inside_f * (sky > 0.5))[..., None] * sky_grad[..., None] * np.array([0.10, 0.10, 0.08], np.float32)
sun_d = np.sqrt((xx - 278) ** 2 + (yy - 370) ** 2)
add += inside_f[..., None] * np.exp(-(sun_d / 110) ** 2)[..., None] * np.array([0.10, 0.09, 0.03], np.float32)
diag = xx + yy * 0.75
streak = (np.exp(-((diag - 560) / 18) ** 2) * 0.55 + np.exp(-((diag - 610) / 7) ** 2) * 0.35 +
          np.exp(-((diag - 900) / 22) ** 2) * 0.35)
add += inside_f[..., None] * streak[..., None] * 0.35

# ---- string lights: each bulb glows
sat = (img.max(-1) - img.min(-1)) > 0.3
bulbs = sat & (yy < 260) & ~lines & (xx < 1240)
bulb_col = np.zeros((H, W, 3), np.float32)
bulb_col[bulbs] = img[bulbs]
halo = np.stack([blur(bulb_col[..., c], 14) for c in range(3)], -1)
norm = blur(bulbs, 14)[..., None] + 1e-4
halo_col = halo / norm
halo_amt = np.clip(blur(bulbs, 13) * 4, 0, 1)[..., None]
add += halo_amt * (halo_col * 0.5 + 0.2) * 0.17 * (1 - lines[..., None])
# a tiny shine dot on each bulb
spec = ndi.shift(bulbs.astype(np.float32), (4, 3), order=0) * bulbs
spec = ndi.binary_erosion(spec > 0.5, iterations=3)
add += blur(spec, 1.2)[..., None] * 0.35

# ---- little objects get round, lit shading (light from the window: top-left)
def round_shade(mask, cx, cy, r, dark=0.30, shine=0.45, sx=-0.38, sy=-0.42, shine_r=0.28):
    """Sphere-ish shading inside mask: darker toward bottom-right, a soft highlight top-left."""
    global shade, add
    dx, dy = (xx - cx) / r, (yy - cy) / r
    rr = np.sqrt(dx ** 2 + dy ** 2)
    lit = np.clip(-(dx * 0.6 + dy * 0.8), -1, 1)                 # facing the light
    shade -= mask * dark * np.clip(0.5 - lit * 0.5, 0, 1) * np.clip(rr, 0.3, 1)
    hl = np.exp(-(((dx - sx) ** 2 + (dy - sy) ** 2) / shine_r ** 2))
    add += (mask * hl)[..., None] * shine


not_wall = (wall < 0.25) & (img.min(-1) < 0.995)
ball = box(815, 262, 897, 330) * near((245, 247, 240), 0.04) * not_wall * ~lines
round_shade(ball, 854, 297, 34, dark=0.32, shine=0.25)
# red stitches stay red: they're not white so they get only a bit of shade
stitches = box(815, 262, 897, 330) * ((img[..., 0] - img[..., 2]) > 0.2)
shade -= stitches * 0.1 * np.clip((xx - 840) / 40, 0, 1)

cam = box(1040, 455, 1158, 516) * ~lines
camgray = cam * (img.max(-1) < 0.45) * (img.max(-1) > 0.15)
# metal sheen: brighter band across the top, darker bottom
shade -= camgray * 0.25 * np.clip((yy - 470) / 45, 0, 1)
add += (camgray * np.exp(-((yy - 476) / 6) ** 2))[..., None] * 0.22
lens_d = np.sqrt((xx - 1100) ** 2 + (yy - 495) ** 2)
add += (cam * np.exp(-(((xx - 1094) ** 2 + (yy - 489) ** 2) / 16)))[..., None] * 0.9    # lens glint
add += (cam * (img.min(-1) > 0.8))[..., None] * 0.0

pot = box(938, 450, 1016, 516) * near((157, 116, 58), 0.08)
shade -= pot * 0.30 * np.clip((xx - 960) / 50, 0, 1) ** 1.3                # round pot: right side in shade
add += (pot * np.exp(-((xx - 955) / 8) ** 2))[..., None] * 0.12
leaves = box(965, 345, 1060, 460) * near((114, 150, 80), 0.10)
shade -= leaves * 0.22 * np.clip((yy - 370) / 60, 0, 1)
add += (leaves * np.clip(1 - (yy - 350) / 40, 0, 1))[..., None] * np.array([0.08, 0.12, 0.05], np.float32)

books = box(680, 245, 812, 333) * ~lines * not_wall * (img.min(-1) < 0.9)
shade -= books * 0.22 * np.clip((xx - 690) / 120, 0, 1)
add += (books * np.exp(-((xx - 692) / 5) ** 2))[..., None] * 0.15

# ---- phone case shine
shade -= case * 0.08 * np.clip((xx - 1500) / 400, 0, 1)
add += case[..., None] * 0.10 * np.exp(-((xx - 1235) / 25) ** 2)[..., None]

# ---- soft drop shadows (things cast them down-right onto the wall)
obj = np.clip(ball + cam + pot + leaves + books, 0, 1)
casters = np.clip(wood + obj, 0, 1)
phone_body = ndi.binary_fill_holes(ndi.binary_closing(case > 0.4, iterations=8)).astype(np.float32)
sh = ndi.shift(blur(casters, 9), (15, 13), order=1)
sh_phone = ndi.shift(blur(phone_body, 26), (30, -34), order=1)
recv = np.clip(wall + floor + rug, 0, 1) * (1 - phone_body)
shade -= recv * (0.20 * np.clip(sh, 0, 1) + 0.22 * np.clip(sh_phone, 0, 1))

# ---- a little paper grain (not on the glass, the objects or the screen)
paper = noise(1, 0.7, 9)
shade -= 0.010 * paper * (1 - inside_f) * (1 - obj) * (1 - wood)
out = np.clip(img * shade[..., None] + add, 0, 1)
keep = np.clip(screen + lines.astype(np.float32), 0, 1)[..., None]
out = out * (1 - keep) + img * keep
Image.fromarray((out * 255 + 0.5).astype(np.uint8)).save(dst, optimize=True)
print("saved", dst)
