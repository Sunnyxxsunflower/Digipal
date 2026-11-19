"""
Renders the desk pet's expression / animation frames from pet.blend.

Run (Terminal):
  "$BL" -b ~/Downloads/pet.blend -P ~/Downloads/animate_pet.py

Writes transparent PNGs to  ~/Downloads/pet_frames/<state>_<nn>.png
States: idle, blink, happy, sleepy, surprised, walk, sing
"""
import math
import os
import sys
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "pet_frames")
os.makedirs(OUT_DIR, exist_ok=True)

scene = bpy.context.scene
HEAD_C = Vector((0, 0, 2.015))
HEAD_R = 0.585
EYE_Z = -0.19


def update():
    bpy.context.view_layer.update()


def empty(name, loc, parent=None):
    e = bpy.data.objects.new(name, None)
    e.location = loc
    bpy.context.collection.objects.link(e)
    update()
    if parent is not None:
        set_parent(e, parent)
    return e


def set_parent(child, parent):
    update()
    mw = child.matrix_world.copy()
    child.parent = parent
    update()
    child.matrix_world = mw


def center_of(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return sum(pts, Vector()) / len(pts)


# ------------------------------------------------------------- rig (simple pivots)
ROOT = empty("Root", (0, 0, 0))
HEAD = empty("HeadPivot", (0, 0, 1.45), ROOT)
ARM = {s: empty("Arm%d" % s, (0.20 * s, 0, 1.37), ROOT) for s in (-1, 1)}
LEG = {s: empty("Leg%d" % s, (0.14 * s, 0, 0.68), ROOT) for s in (-1, 1)}
TAIL = {s: empty("TailPivot%d" % s, (0.5 * s, 0, 2.40), HEAD) for s in (-1, 1)}

eye_mat = None
parts = [o for o in list(scene.objects) if o.type in ("MESH", "CURVE")]
for o in parts:
    if o.hide_render:
        continue
    n = o.name
    if n.startswith("Eye") and eye_mat is None and o.data.materials:
        eye_mat = o.data.materials[0]
    if n.startswith("Tail"):
        set_parent(o, TAIL[-1 if "-1" in n else 1])
        continue
    if n.startswith(("Head", "Hair", "Eye", "Bang")):
        set_parent(o, HEAD)
        continue
    c = center_of(o)
    if c.z > 1.5:
        set_parent(o, HEAD)
    elif abs(c.x) > 0.17 and c.z > 0.85:
        set_parent(o, ARM[1 if c.x > 0 else -1])
    elif abs(c.x) > 0.05 and c.z < 0.7:
        set_parent(o, LEG[1 if c.x > 0 else -1])
    else:
        set_parent(o, ROOT)

# the original ^ ^ eyes become one of several swappable eye shapes
original_eyes = [o for o in scene.objects if o.name.startswith("Eye")]


def on_visor(x, z):
    y = -math.sqrt(max(0.0001, HEAD_R ** 2 - x ** 2 - z ** 2)) - 0.012
    return (x, y, z + HEAD_C.z)


def eye_shape(name, pts, cyclic=False):
    objs = []
    for side in (-1, 1):
        cu = bpy.data.curves.new("%s%d" % (name, side), "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = 0.02
        cu.bevel_resolution = 4
        spl = cu.splines.new("POLY")
        spl.points.add(len(pts) - 1)
        for i, (dx, dz) in enumerate(pts):
            x, y, z = on_visor(0.26 * side + dx, EYE_Z + dz)
            spl.points[i].co = (x, y, z, 1.0)
        spl.use_cyclic_u = cyclic
        o = bpy.data.objects.new("%s%d" % (name, side), cu)
        bpy.context.collection.objects.link(o)
        if eye_mat is not None:
            o.data.materials.append(eye_mat)
        set_parent(o, HEAD)
        objs.append(o)
    return objs


N = 12
EYES = {
    "caret": original_eyes,
    "line": eye_shape("EyeLine", [(-0.11, -0.01), (0.11, -0.01)]),
    "sleepy": eye_shape("EyeSleepy", [(-0.11 + 0.22 * i / N,
                                        -0.01 - 0.035 * (1 - ((-0.11 + 0.22 * i / N) / 0.11) ** 2))
                                       for i in range(N + 1)]),
    "circle": eye_shape("EyeO", [(0.075 * math.cos(2 * math.pi * i / 20),
                                  0.075 * math.sin(2 * math.pi * i / 20))
                                 for i in range(20)], cyclic=True),
}

# pink blush ovals
blush_mat = bpy.data.materials.new("blush")
blush_mat.use_nodes = True
nt = blush_mat.node_tree
nt.nodes.clear()
em = nt.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value = (1.0, 0.35, 0.55, 1.0)
em.inputs["Strength"].default_value = 1.6
out = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
BLUSH = []
for side in (-1, 1):
    x, y, z = on_visor(0.36 * side, -0.31)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.06,
                                         location=(x, y + 0.02, z))
    b = bpy.context.active_object
    b.name = "Blush%d" % side
    b.scale = (1.3, 0.25, 0.7)
    b.data.materials.append(blush_mat)
    set_parent(b, HEAD)
    BLUSH.append(b)

# headphones (only shown while she sings along to music)
def make_headphones():
    import bmesh
    blue = bpy.data.materials.get("blue")
    dark = bpy.data.materials.get("gray_dark")
    blk = bpy.data.materials.get("black")
    parts = []
    bpy.ops.mesh.primitive_torus_add(major_radius=HEAD_R + 0.075, minor_radius=0.038,
                                     major_segments=64, minor_segments=12,
                                     location=HEAD_C, rotation=(math.pi / 2, 0, 0))
    band = bpy.context.active_object
    bm = bmesh.new()
    bm.from_mesh(band.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.y < -0.02], context="VERTS")
    bm.to_mesh(band.data)
    bm.free()
    parts.append((band, dark))
    for side in (-1, 1):
        bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=0.17, depth=0.14,
                                            location=(side * (HEAD_R + 0.06), 0, HEAD_C.z - 0.02),
                                            rotation=(0, math.pi / 2, 0))
        parts.append((bpy.context.active_object, blue))
        bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=0.11, depth=0.03,
                                            location=(side * (HEAD_R + 0.135), 0, HEAD_C.z - 0.02),
                                            rotation=(0, math.pi / 2, 0))
        parts.append((bpy.context.active_object, dark))
    out = []
    for o, m in parts:
        o.name = "Headphones"
        if m is not None:
            o.data.materials.append(m)
        for poly in o.data.polygons:
            poly.use_smooth = True
        o.hide_render = True
        set_parent(o, HEAD)
        out.append(o)
    return out


HEADPHONES = make_headphones()

# ------------------------------------------------------------- nap beds
def prop_mat(name, hexcol, rough=0.6, stripes=None, glow=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    if glow is not None:
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = glow
        em.inputs["Strength"].default_value = 4.0
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
        return m
    h = hexcol.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb]
    b = nt.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1)
    b.inputs["Roughness"].default_value = rough
    if stripes:
        h2 = stripes.lstrip("#")
        rgb2 = [int(h2[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin2 = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb2]
        wv = nt.nodes.new("ShaderNodeTexWave")
        wv.wave_type = "BANDS"
        wv.bands_direction = "Z"
        wv.wave_profile = "SAW"
        wv.inputs["Scale"].default_value = 6.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"
        ramp.color_ramp.elements[0].color = (lin[0], lin[1], lin[2], 1)
        ramp.color_ramp.elements[1].position = 0.55
        ramp.color_ramp.elements[1].color = (lin2[0], lin2[1], lin2[2], 1)
        nt.links.new(wv.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return m


def soft_box(name, loc, size, mat, bevel=0.08):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bv = o.modifiers.new("Soft", "BEVEL")
    bv.width = bevel
    bv.segments = 6
    o.data.materials.append(mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    o.hide_render = True
    return o


def squashed_ball(name, loc, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    o.data.materials.append(mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    o.hide_render = True
    return o


cream = prop_mat("bed_cream", "#f3ead8")
white = prop_mat("bed_white", "#fbfbff", 0.7)
blanket_mat = prop_mat("bed_blanket", "#9fb2e6", 0.8, stripes="#f7f3ff")
pink = prop_mat("bed_pink", "#f2a7c3", 0.75)
pad = prop_mat("bed_pad", "#fff3f7", 0.8)
dock_gray = prop_mat("dock_gray", "#3b3d45", 0.4)
dock_glow = prop_mat("dock_glow", None, glow=(0.35, 0.85, 1.0, 1.0))

# A. futon: mattress, pillow, striped blanket
futon_mattress = soft_box("FutonMattress", (-0.1, 0.05, 0.08), (2.75, 1.2, 0.16), cream)
futon_pillow = squashed_ball("FutonPillow", (0.6, 0.05, 0.33), (0.55, 0.45, 0.18), white)
# blanket: a long rounded roll lying along the futon, tucked up to her neck
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.5, depth=1.85,
                                    location=(-0.62, -0.02, 0.5),
                                    rotation=(0, math.pi / 2, 0))
BLANKET = bpy.context.active_object
BLANKET.name = "FutonBlanket"
BLANKET.scale = (1, 1.15, 1)
_bv = BLANKET.modifiers.new("Soft", "BEVEL")
_bv.width = 0.12
_bv.segments = 8
BLANKET.data.materials.append(blanket_mat)
for poly in BLANKET.data.polygons:
    poly.use_smooth = True
BLANKET.hide_render = True
BLANKET_Z = 0.5

# B. round pet bed
bpy.ops.mesh.primitive_torus_add(major_radius=0.66, minor_radius=0.22, major_segments=64,
                                 minor_segments=20, location=(0, 0.1, 0.2))
pet_rim = bpy.context.active_object
pet_rim.name = "PetBedRim"
pet_rim.scale = (1, 1, 0.85)
pet_rim.rotation_euler = (math.radians(-8), 0, 0)
pet_rim.data.materials.append(pink)
for poly in pet_rim.data.polygons:
    poly.use_smooth = True
pet_rim.hide_render = True
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.56, depth=0.14, location=(0, 0.1, 0.08))
pet_pad = bpy.context.active_object
pet_pad.name = "PetBedPad"
pet_pad.rotation_euler = (math.radians(-8), 0, 0)
pet_pad.data.materials.append(pad)
pet_pad.hide_render = True

# C. charging dock: base, glowing ring, little post with a plug light
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.6, depth=0.12, location=(0, 0, 0.06))
dock_base = bpy.context.active_object
dock_base.name = "DockBase"
dock_base.data.materials.append(dock_gray)
dock_base.hide_render = True
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.615, depth=0.035, location=(0, 0, 0.06))
dock_ring = bpy.context.active_object
dock_ring.name = "DockRing"
dock_ring.data.materials.append(dock_glow)
dock_ring.hide_render = True
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.05, depth=1.3, location=(0.62, 0.25, 0.7))
dock_post = bpy.context.active_object
dock_post.name = "DockPost"
dock_post.data.materials.append(dock_gray)
dock_post.hide_render = True
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.09, location=(0.62, 0.25, 1.38))
dock_light = bpy.context.active_object
dock_light.name = "DockLight"
dock_light.data.materials.append(dock_glow)
dock_light.hide_render = True

PROPS = {
    "futon": [futon_mattress, futon_pillow, BLANKET],
    "petbed": [pet_rim, pet_pad],
    "dock": [dock_base, dock_ring, dock_post, dock_light],
}

# ------------------------------------------------------------- 3D outfits
def outfit_mat(name, hexcol, rough=0.6):
    return prop_mat(name, hexcol, rough)


red = outfit_mat("of_red", "#d9363e")
fluff = outfit_mat("of_white", "#fbfbff", 0.9)
witch = outfit_mat("of_witch", "#2e2342", 0.7)
orange = outfit_mat("of_orange", "#f0a030")
petal = outfit_mat("of_petal", "#ffb3d1")
yolk = outfit_mat("of_yellow", "#ffd54f")
ear_in = outfit_mat("of_earpink", "#f27fa8")
hair_mat = bpy.data.materials.get("hair") or witch
blue_mat = bpy.data.materials.get("blue")


def part(o, mat, parent, smooth=True):
    o.data.materials.append(mat)
    if smooth:
        for poly in o.data.polygons:
            poly.use_smooth = True
    o.hide_render = True
    set_parent(o, parent)
    return o


def made():
    return bpy.context.active_object


OUTFITS = {k: [] for k in ("santa", "witch", "ears", "flower", "scarf", "party", "heart",
                            "sunhat", "beret", "bunny", "glasses", "bow", "star")}

# witch hat: built as ONE hat (brim, crown, band share one frame), then set on her head
def hat_part(o, mat, frame, loc, rot=(0, 0, 0)):
    o.data.materials.append(mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    o.hide_render = True
    o.parent = frame
    o.matrix_parent_inverse.identity()
    o.location = loc
    o.rotation_euler = rot
    return o


# sits on the very top of her head, above her twin tails (they reach about z 2.55)
# the first hat's shape (narrow, tall, pointy), just scaled up, sitting above her twin tails.
# (anything above about z 3.28 would be cut off by the top of her window, so it stops there)
WITCH = empty("WitchHatFrame", (0.0, 0, 2.535), HEAD)
WITCH.rotation_euler = (math.radians(6), 0, 0)
bpy.ops.mesh.primitive_cylinder_add(vertices=72, radius=1.04, depth=0.05)
brim = made()
bv = brim.modifiers.new("Soft", "BEVEL")
bv.width = 0.02
bv.segments = 3
OUTFITS["witch"].append(hat_part(brim, witch, WITCH, (0, 0, 0)))
bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.58, radius2=0.0, depth=0.72)
OUTFITS["witch"].append(hat_part(made(), witch, WITCH, (0, 0, 0.38)))
# band: a thin slice that hugs the bottom of the crown
bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.6, radius2=0.53, depth=0.09)
OUTFITS["witch"].append(hat_part(made(), orange, WITCH, (0, 0, 0.07)))

# santa hat: one soft hat. A red crown wide enough to cover the top of her head,
# folding over to the side, a fluffy white cuff hugging its base, and a pompom.
SANTA = empty("SantaHatFrame", (0.0, 0, 2.5), HEAD)
SANTA.rotation_euler = (math.radians(6), 0, math.radians(0))
bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.63, radius2=0.33, depth=0.36)
OUTFITS["santa"].append(hat_part(made(), red, SANTA, (0, 0, 0.2)))
# the floppy top leans over to her right
FLOP = empty("SantaFlop", (0, 0, 0), SANTA)
FLOP.parent = SANTA
FLOP.matrix_parent_inverse.identity()
FLOP.location = (0, 0, 0.36)
FLOP.rotation_euler = (0, math.radians(62), 0)
bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.33, radius2=0.03, depth=0.5)
OUTFITS["santa"].append(hat_part(made(), red, FLOP, (0, 0, 0.23)))
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.11)
OUTFITS["santa"].append(hat_part(made(), fluff, FLOP, (0, 0, 0.5)))
# a soft joint so the bend looks smooth
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.33)
OUTFITS["santa"].append(hat_part(made(), red, SANTA, (0, 0, 0.37)))
# fluffy cuff
bpy.ops.mesh.primitive_torus_add(major_radius=0.64, minor_radius=0.11, major_segments=64,
                                 minor_segments=20)
OUTFITS["santa"].append(hat_part(made(), fluff, SANTA, (0, 0, 0.04)))

# cat ears: built point by point so the left and right ears are exact mirror images
def ear_mesh(name, half_w, back, front, height, tip_fwd):
    """A little pyramid: wide flat front, narrow back, pointy tip. Base at z=0."""
    import bmesh
    bm = bmesh.new()
    fl = bm.verts.new((-half_w, -front, 0))
    fr = bm.verts.new((half_w, -front, 0))
    bk = bm.verts.new((0, back, 0))
    tip = bm.verts.new((0, -tip_fwd, height))
    bm.faces.new((fl, fr, tip))      # the front face you see
    bm.faces.new((fr, bk, tip))
    bm.faces.new((bk, fl, tip))
    bm.faces.new((fl, bk, fr))       # bottom (tucked in her hair)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


for sx in (-1, 1):
    ang = math.radians(30) * sx
    sink = 0.12                                   # tuck the base into her hair
    r = 0.605 - sink
    base = (r * math.sin(ang), 0.0, 2.015 + r * math.cos(ang))
    for name, mat, half_w, back, front, height, tip_fwd, dy, up in (
            ("EarOuter", hair_mat, 0.24, 0.09, 0.05, 0.50, 0.0, 0.0, 0.0),
            ("EarInner", ear_in, 0.14, 0.0, 0.07, 0.30, 0.03, -0.012, 0.07)):
        o = ear_mesh("%s%d" % (name, sx), half_w, back, front, height, tip_fwd)
        o.location = (base[0] + math.sin(ang) * up, dy, base[2] + math.cos(ang) * up)
        o.rotation_euler = (0, ang, 0)
        OUTFITS["ears"].append(part(o, mat, HEAD, smooth=False))

# flower: flat like a sticker, lying on the top-right of her hair, facing out
n = Vector((0.4, -0.5, 0.77)).normalized()
FLOWER = empty("FlowerFrame", tuple(HEAD_C + n * 0.612), HEAD)
FLOWER.rotation_euler = n.to_track_quat("Z", "Y").to_euler()
for k in range(5):
    a = math.radians(k * 72 + 90)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=10, radius=0.1)
    o = made()
    o.scale = (1, 1, 0.3)
    OUTFITS["flower"].append(hat_part(o, petal, FLOWER, (0.12 * math.cos(a), 0.12 * math.sin(a), 0)))
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.07)
o = made()
o.scale = (1, 1, 0.45)
OUTFITS["flower"].append(hat_part(o, yolk, FLOWER, (0, 0, 0.02)))

# scarf: a ring around her neck and a tail down the front
bpy.ops.mesh.primitive_torus_add(major_radius=0.23, minor_radius=0.075, major_segments=48,
                                 minor_segments=16, location=(0, 0, 1.455))
OUTFITS["scarf"].append(part(made(), red, ROOT))
bpy.ops.mesh.primitive_cube_add(size=1, location=(0.12, -0.25, 1.26), rotation=(0, math.radians(-8), 0))
o = made()
o.scale = (0.11, 0.06, 0.32)
bv = o.modifiers.new("Soft", "BEVEL")
bv.width = 0.03
bv.segments = 4
OUTFITS["scarf"].append(part(o, red, ROOT))

# party hat (New Year's and birthdays): a little striped cone on the top-right of her head,
# tilted out, with a pink pompom. Sits on the head surface like the flower does.
party_blue = outfit_mat("of_partyblue", "#7ec8f0", 0.5)
n = Vector((0.3, -0.12, 0.95)).normalized()
PARTY = empty("PartyHatFrame", tuple(HEAD_C + n * 0.58), HEAD)
PARTY.rotation_euler = n.to_track_quat("Z", "Y").to_euler()
bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.25, radius2=0.012, depth=0.6)
OUTFITS["party"].append(hat_part(made(), party_blue, PARTY, (0, 0, 0.3)))
# yellow stripes: thin slices that hug the cone (slightly bigger so they sit on its surface)
for z0, h in ((0.1, 0.07), (0.3, 0.06), (0.47, 0.045)):
    zc = z0 + h / 2
    r_at = lambda z: 0.25 + (0.012 - 0.25) * (z / 0.6)
    bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=r_at(z0) + 0.008, radius2=r_at(z0 + h) + 0.008,
                                    depth=h)
    OUTFITS["party"].append(hat_part(made(), yolk, PARTY, (0, 0, zc)))
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.075)
OUTFITS["party"].append(hat_part(made(), ear_in, PARTY, (0, 0, 0.62)))

# heart clip (Valentine's week): a puffy pink heart lying on the top-left of her hair,
# facing out like a sticker (the flower's twin on the other side)
def heart_mesh(name, size, thick):
    import bmesh
    bm = bmesh.new()
    vs = []
    for k in range(48):
        t = 2 * math.pi * k / 48
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        vs.append(bm.verts.new((x * size, (y + 4.5) * size, 0)))  # lobes up, centered
    f = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    moved = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, thick), verts=moved)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bv = o.modifiers.new("Puffy", "BEVEL")
    bv.width = thick * 0.45
    bv.segments = 5
    bv.limit_method = "NONE"
    return o


heart_pink = outfit_mat("of_heart", "#f25c8a", 0.45)
n = Vector((-0.4, -0.5, 0.77)).normalized()
HEART = empty("HeartClipFrame", tuple(HEAD_C + n * 0.6), HEAD)
HEART.rotation_euler = n.to_track_quat("Z", "Y").to_euler()
OUTFITS["heart"].append(hat_part(heart_mesh("HeartClip", 0.0085, 0.06), heart_pink, HEART, (0, 0, 0)))

# ---- round 3 accessories -------------------------------------------------------------------
def local_empty(name, parent, loc=(0, 0, 0), rot=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(e)
    e.parent = parent
    e.matrix_parent_inverse.identity()
    e.location = loc
    e.rotation_euler = rot
    return e


def on_head(n, dist, name):
    """A frame sitting on her head surface at direction n, facing out."""
    n = Vector(n).normalized()
    fr = empty(name, tuple(HEAD_C + n * dist), HEAD)
    fr.rotation_euler = n.to_track_quat("Z", "Y").to_euler()
    return fr


# summer sun hat: a wide floppy straw brim, a rounded crown, a ribbon band with a little bow
straw = prop_mat("of_straw", "#ecd393", 0.85, stripes="#d8b86a")
ribbon_blue = outfit_mat("of_ribbon", "#7fb6e8", 0.5)
SUNHAT = empty("SunHatFrame", (0.0, 0, 2.28), HEAD)            # pulled down over her hair
SUNHAT.rotation_euler = (math.radians(6), math.radians(-5), 0)
bpy.ops.mesh.primitive_cone_add(vertices=96, radius1=1.3, radius2=0.8, depth=0.14)
o = made()
bv = o.modifiers.new("Soft", "BEVEL")
bv.width = 0.035
bv.segments = 3
OUTFITS["sunhat"].append(hat_part(o, straw, SUNHAT, (0, 0, 0.0)))               # brim, sloping down
bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.8, depth=0.5)
o = made()
bv = o.modifiers.new("Soft", "BEVEL")
bv.width = 0.18
bv.segments = 8
OUTFITS["sunhat"].append(hat_part(o, straw, SUNHAT, (0, 0, 0.28)))               # big rounded crown
bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.815, depth=0.12)
OUTFITS["sunhat"].append(hat_part(made(), ribbon_blue, SUNHAT, (0, 0, 0.13)))    # ribbon band
for sx in (-1, 1):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=10, radius=0.11)
    o = made()
    o.scale = (1.3, 0.5, 0.75)
    OUTFITS["sunhat"].append(hat_part(o, ribbon_blue, SUNHAT, (0.53 + 0.11 * sx, -0.56, 0.14),
                                      (0, math.radians(20 * sx), math.radians(-45))))


# ---- the real straw hat: "Straw-Hat with 2 Shape-Keys" by grs (Blend Swap, CC0). If it's in
# studio/models, it replaces the simple one above: fitted so the crown hugs her hair and the
# brim is as wide as ours, in our own straw and ribbon colors.
SUNHAT_BLEND = os.path.join(HERE, "models", "StrawHat.blend")
SUNHAT_BRIM_R, SUNHAT_CROWN_R = 1.3, 0.8
SUNHAT_SHAPES = {}                       # the model's own droopy pose squashes the crown, so:
SUNHAT_CROWN_UP = 1.08                   # its plain shape (crown a touch taller), and
SUNHAT_DROOP = (0.24, 0.10)              # our own big floppy droop: all around, plus extra at her sides


def import_strawhat(path, keys=None):
    """keys: shape key name -> value (the model's own floppier brim poses)."""
    keys = keys or {}
    info = []
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith("Strawhat") or n == "Band"]
    objs = [o for o in dst.objects if o is not None and o.type == "MESH"]
    for o in objs:
        bpy.context.collection.objects.link(o)
    update()
    # bake each piece's placement into its mesh (and its shape keys), then forget parents
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = None
        o.data.transform(mw)
        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks:
                for d in kb.data:
                    d.co = mw @ d.co
        o.matrix_world = Matrix()
        info.append("%s: verts %d, modifiers %s, shape keys %s" % (
            o.name, len(o.data.vertices), [(m.type, m.name) for m in o.modifiers],
            [kb.name for kb in o.data.shape_keys.key_blocks] if o.data.shape_keys else None))
    body = next(o for o in objs if o.name.startswith("Strawhat") and "Ribbon" not in o.name)
    vs = [v.co.copy() for v in body.data.vertices]
    cx = (min(v.x for v in vs) + max(v.x for v in vs)) / 2
    cy = (min(v.y for v in vs) + max(v.y for v in vs)) / 2
    rr = [math.hypot(v.x - cx, v.y - cy) for v in vs]
    rmax = max(rr)
    brim_z = sorted(v.z for v, r in zip(vs, rr) if r > 0.75 * rmax)
    brim_top = brim_z[int(len(brim_z) * 0.9)]
    crown = [(v, r) for v, r in zip(vs, rr) if v.z > brim_top + 0.02 * rmax and r < 0.7 * rmax]
    ztop = max(v.z for v in vs)
    low = sorted(r for v, r in crown if v.z < brim_top + (ztop - brim_top) * 0.4) or [rmax * 0.5]
    crown_r = low[int(len(low) * 0.9)]
    info.append("raw: center (%.3f, %.3f), brim radius %.3f, brim top z %.3f, crown radius %.3f, "
                "top z %.3f, z min %.3f" % (cx, cy, rmax, brim_top, crown_r, ztop, min(v.z for v in vs)))
    s = SUNHAT_BRIM_R / rmax
    c = crown_r * s
    f = max(1.0, SUNHAT_CROWN_R / c)            # widen just the crown if it's too small for her hair
    c2 = max(c * 1.35, c * f * 1.1)

    def fit(p):
        q = Vector(((p.x - cx) * s, (p.y - cy) * s, (p.z - brim_top) * s))
        r = math.hypot(q.x, q.y)
        if r > 1e-6 and f > 1.0:
            if r <= c:
                k = f
            elif r < c2:
                k = (c * f + (r - c) * (c2 - c * f) / (c2 - c)) / r
            else:
                k = 1.0
            q.x *= k
            q.y *= k
        r = math.hypot(q.x, q.y)
        edge = c * f                           # where the crown meets the brim
        if r < edge * 1.02 and q.z > 0:
            q.z *= SUNHAT_CROWN_UP
        if r > edge * 1.05:                    # the brim curves gently down, more at her sides
            t = min(1.0, (r - edge * 1.05) / (SUNHAT_BRIM_R - edge * 1.05))
            side = (q.x / r) ** 2
            q.z -= (SUNHAT_DROOP[0] + SUNHAT_DROOP[1] * side) * t ** 1.5
        return q

    for o in objs:
        for v in o.data.vertices:
            v.co = fit(v.co)
        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks:
                for d in kb.data:
                    d.co = fit(d.co)
        for m in o.modifiers:                   # sizes in modifiers scale with the hat
            for attr in ("thickness", "width"):
                if isinstance(getattr(m, attr, None), float):
                    setattr(m, attr, getattr(m, attr) * s)
        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = keys.get(kb.name, 0.0)
        o.data.materials.clear()
        for poly in o.data.polygons:
            poly.material_index = 0
    info.append("fit: scale %.3f, crown widened x%.2f" % (s, f))
    try:
        with open(os.path.join(HERE, "sunhat_info.txt"), "w") as fh:
            fh.write("\n".join(info) + "\n")
    except OSError:
        pass
    parts = []
    for o in objs:
        mat = straw if o is body else ribbon_blue
        parts.append(hat_part(o, mat, SUNHAT, (0, 0, 0)))
    return parts


if os.path.exists(SUNHAT_BLEND):
    for o in OUTFITS["sunhat"]:
        bpy.data.objects.remove(o, do_unlink=True)
    OUTFITS["sunhat"] = import_strawhat(SUNHAT_BLEND, SUNHAT_SHAPES)

def rod(a, b, radius, mat, parent):
    """A thin bar from a to b (like stick(), which is defined further down)."""
    a, b = Vector(a), Vector(b)
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius, depth=d.length, location=(a + b) / 2)
    o = made()
    o.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    o.data.materials.append(mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    o.hide_render = True
    set_parent(o, parent)
    return o


# autumn beret with a little leaf pin
beret_red = outfit_mat("of_beret", "#702124", 0.8)       # the studio lights lift it to about #a23b3f
leaf_orange = outfit_mat("of_leaf", "#e8833a", 0.6)
# a felt beret like Nancy's reference: a short straight headband, and a big soft pillowy top that
# overhangs it, drooping down on one side (you can see the band under the other side),
# with a little curved stalk on top
BERET = empty("BeretFrame", (0.06, 0.02, 2.3), HEAD)       # the band sits low, hugging her head
BERET.rotation_euler = (math.radians(7), math.radians(6), 0)
BERET_R, BERET_ZC, BERET_HT, BERET_HB = 0.78, 0.25, 0.19, 0.11    # cushion: radius, center, top/bottom
BERET_PIVOT = 0.13                             # where the band ends and the drooping top begins
BERET_DROOP = (math.radians(-3), math.radians(-9), 0)
FOLD_AT, FOLD_SPAN, FOLD_Z = math.radians(-40), math.radians(70), 0.05   # where the band's fold goes


def beret_mesh(name, hc=None):
    """The whole beret as ONE smooth spun shape, so the band and the top can never come apart:
    a straight headband that flows into a soft cushion top, which then droops to one side."""
    import bmesh
    from mathutils import Euler, Quaternion
    prof = [(0.47, -0.16), (0.50, -0.11), (0.515, -0.07), (0.525, -0.05), (0.535, -0.03)]
    for k in range(31):                        # the band, straight up, tucking under the cushion
        z = -0.01 + 0.13 * k / 30              # (close rows, so the fold below has room to bend)
        prof.append((0.54 - 0.008 * max(0.0, (z - 0.09) / 0.03), z))
    nb = len(prof) - 1                         # band rows (the first few tuck down inside her head)
    th0 = -math.acos(prof[-1][0] / BERET_R)
    steps = 40
    for k in range(1, steps + 1):              # cushion: underside out to the edge, over the top
        th = th0 + (math.pi / 2 - th0) * k / steps
        s = math.sin(th)
        h = BERET_HT if s > 0 else BERET_HB
        r = BERET_R * math.cos(th)
        prof.append((max(r, 0.0), BERET_ZC + h * math.copysign(abs(s) ** 0.62, s)))
    prof[-1] = (0.0, prof[-1][1])
    q_full = Euler(BERET_DROOP).to_quaternion()
    ident = Quaternion()
    piv = Vector((0, 0, BERET_PIVOT))

    def tilt(z, band):
        # bottom stays on her head, top tilts with the cushion: so the band is short on the
        # drooping side and taller on the other
        return min(1.0, max(0.0, (z + 0.05) / 0.17)) if band else 1.0

    def fold_w(a):
        # the soft fold in the band, across the front-right (where Nancy drew it)
        d = math.atan2(math.sin(a - FOLD_AT), math.cos(a - FOLD_AT))
        return math.cos(d / FOLD_SPAN * math.pi / 2) ** 2 if abs(d) < FOLD_SPAN else 0.0

    def fold_dr(z):
        # a little puff of felt above the crease, and the crease tucked in under it
        return (0.016 * math.exp(-((z - FOLD_Z - 0.02) / 0.013) ** 2)
                - 0.012 * math.exp(-((z - FOLD_Z) / 0.007) ** 2))

    def place(r, z, a, band):
        t = tilt(z, band)
        q = ident.slerp(q_full, t)
        p = Vector((r * math.cos(a), r * math.sin(a), z))
        return q @ (p - piv) + piv + Vector((0.02 * t, 0, 0))

    N = 96
    bm = bmesh.new()
    rings = []
    for idx, (r, z) in enumerate(prof):
        band = idx <= nb
        ring = []
        cnt = 1 if r == 0 else N
        for i in range(cnt):
            a = 2 * math.pi * i / N
            rr = r + (fold_dr(z) * fold_w(a) if band else 0.0)
            ring.append(bm.verts.new(place(rr, z, a, band)))
        rings.append(ring)
    crease = []                                # the inked line along the crease
    for k in range(41):
        a = FOLD_AT - FOLD_SPAN * 0.8 + FOLD_SPAN * 1.6 * k / 40
        w = fold_w(a)
        zc = FOLD_Z + 0.01                     # along the lower lip of the puff, so it shows
        # sit just outside the felt everywhere around it, so no bit of the line sinks in and breaks
        rs = max(0.54 + fold_dr(zc + dz * 0.001) * w for dz in range(-9, 10))
        crease.append((place(rs + 0.0045, zc, a, True),
                       math.sin(math.pi * k / 40) ** 0.6))
    for row, (ra, rb) in enumerate(zip(rings, rings[1:])):
        for i in range(N):
            j = (i + 1) % N
            if len(rb) == 1:
                f = bm.faces.new((ra[i], ra[j], rb[0]))
            else:
                f = bm.faces.new((ra[i], ra[j], rb[j], rb[i]))
            f.material_index = 1 if row < nb else 0      # the band is a darker red
    bm.faces.new(list(reversed(rings[0]))).material_index = 1     # close the bottom (inside her head)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    line = []                                  # where the band meets her head, all the way around
    if hc is not None:
        for i in range(N):
            col = [rings[k][i].co.copy() for k in range(nb + 14)]     # band, then the cushion's underside
            hit = col[0]
            for k in range(1, len(col)):
                d0, d1 = (col[k - 1] - hc).length, (col[k] - hc).length
                if d0 <= HEAD_R < d1:
                    f = (HEAD_R - d0) / (d1 - d0)
                    hit = col[k - 1].lerp(col[k], f)
                    break
            out = Vector((hit.x, hit.y, 0)).normalized()
            line.append(hit + out * 0.004)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o, line, crease


def ring_tube(name, pts, rad, sides=6):
    """A thin closed tube through pts: a drawn-on outline line."""
    import bmesh
    bm = bmesh.new()
    n = len(pts)
    circ = []
    for i in range(n):
        p, tan = pts[i], (pts[(i + 1) % n] - pts[i - 1]).normalized()
        side = tan.cross(Vector((0, 0, 1))).normalized()
        up = side.cross(tan).normalized()
        circ.append([bm.verts.new(p + (side * math.cos(2 * math.pi * k / sides) +
                                       up * math.sin(2 * math.pi * k / sides)) * rad)
                     for k in range(sides)])
    for i in range(n):
        a, b = circ[i], circ[(i + 1) % n]
        for k in range(sides):
            m = (k + 1) % sides
            bm.faces.new((a[k], a[m], b[m], b[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def open_tube(name, pts, rad, sides=6):
    """A thin open tube through (point, thickness 0..1) pairs: an inked line with tapered ends."""
    import bmesh
    bm = bmesh.new()
    n = len(pts)
    circ = []
    for i, (p, k) in enumerate(pts):
        tan = (pts[min(i + 1, n - 1)][0] - pts[max(i - 1, 0)][0]).normalized()
        side = tan.cross(Vector((0, 0, 1))).normalized()
        up = side.cross(tan).normalized()
        r = rad * max(k, 0.15)
        circ.append([bm.verts.new(p + (side * math.cos(2 * math.pi * j / sides) +
                                       up * math.sin(2 * math.pi * j / sides)) * r)
                     for j in range(sides)])
    for i in range(n - 1):
        a, b = circ[i], circ[i + 1]
        for j in range(sides):
            m = (j + 1) % sides
            bm.faces.new((a[j], a[m], b[m], b[j]))
    bm.faces.new(list(reversed(circ[0])))
    bm.faces.new(circ[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


beret_band = outfit_mat("of_beret_band", "#6b1b1e", 0.85)          # renders about #7a2a2e, darker than the top


def contact_line(m, dist=0.02, below=None):
    """Draw a black outline on this material wherever it touches something (her head or her hair),
    like an inked line. `below`: only on the part under that object z (None: everywhere)."""
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.samples = 16
    ao.only_local = False
    ao.inputs["Distance"].default_value = dist
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.55
    ramp.color_ramp.elements[0].color = (1, 1, 1, 1)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = (0, 0, 0, 1)
    nt.links.new(ao.outputs["AO"], ramp.inputs["Fac"])
    if below is None:
        fac = ramp.outputs["Color"]
    else:
        fac = _below_mask(nt, ramp, below)
    ink = nt.nodes.new("ShaderNodeEmission")
    ink.inputs["Color"].default_value = (0.006, 0.005, 0.006, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(fac, mix.inputs["Fac"])
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    nt.links.new(ink.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])


def _below_mask(nt, ramp, below):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    low = nt.nodes.new("ShaderNodeMapRange")
    low.inputs["From Min"].default_value = below + 0.03
    low.inputs["From Max"].default_value = below
    low.clamp = True
    nt.links.new(sep.outputs["Z"], low.inputs["Value"])
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.use_clamp = True
    nt.links.new(ramp.outputs["Color"], mul.inputs[0])
    nt.links.new(low.outputs["Result"], mul.inputs[1])
    return mul.outputs["Value"]


# (the line where the beret rests on her HAIR is inked in by cutout_layer, from a mask of the hat)
update()
o, _line, _crease = beret_mesh("Beret", BERET.matrix_world.inverted() @ HEAD_C)
o = hat_part(o, beret_red, BERET, (0, 0, 0))
o.data.materials.append(beret_band)
OUTFITS["beret"].append(o)
line_black = outfit_mat("of_line", "#141014", 0.9)
OUTFITS["beret"].append(hat_part(ring_tube("BeretEdgeLine", _line, 0.006), line_black, BERET, (0, 0, 0)))
OUTFITS["beret"].append(hat_part(open_tube("BeretFoldLine", _crease, 0.0055), line_black, BERET, (0, 0, 0)))
# TOP: the drooped cushion's own space (same tilt as the mesh), for the stalk and the leaf pin
TOP = local_empty("BeretTop", BERET, (0.02, 0, BERET_PIVOT), BERET_DROOP)


def puff_z(x, y):
    """Height of the beret's top surface at (x, y), in TOP's space."""
    r = min(0.999, math.hypot(x, y) / BERET_R)
    return BERET_ZC - BERET_PIVOT + BERET_HT * (1 - r * r) ** 0.31


pts = [Vector((0.03, 0.02, puff_z(0.03, 0.02) - 0.03))]
for dx, dz in ((0.0, 0.08), (0.015, 0.05), (0.04, 0.03), (0.045, 0.0)):
    pts.append(pts[-1] + Vector((dx, 0, dz)))
for k in range(len(pts) - 1):
    p0, p1 = pts[k], pts[k + 1]
    d = p1 - p0
    rad = 0.022 - 0.003 * k
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=rad, depth=d.length)
    OUTFITS["beret"].append(hat_part(made(), beret_red, TOP, tuple((p0 + p1) / 2),
                                     tuple(d.to_track_quat("Z", "Y").to_euler())))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=rad)
    OUTFITS["beret"].append(hat_part(made(), beret_red, TOP, tuple(p1)))

leaf_red = outfit_mat("of_leaf2", "#c2512b", 0.6)
leaf_vein = outfit_mat("of_vein", "#8a3a1c", 0.6)
gold_pin = outfit_mat("of_goldpin", "#d8cc78", 0.45)    # pale butter yellow


def leaf_mesh(name, length, width, thick):
    """A pointed leaf, slightly toothed at the edge."""
    import bmesh
    bm = bmesh.new()
    pts = []
    N = 28
    for k in range(N + 1):                       # one side, tip to stem
        t = k / N
        w = width * math.sin(math.pi * t) ** 0.8
        pts.append((w, length * (0.5 - t)))
    for k in range(N - 1, 0, -1):                # the other side, back up
        x, y = pts[k]
        pts.append((-x, y))
    vs = [bm.verts.new((x, y, 0)) for x, y in pts]
    f = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    moved = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, thick), verts=moved)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bv = o.modifiers.new("Soft", "BEVEL")
    bv.width = thick * 0.4
    bv.segments = 3
    bv.limit_method = "NONE"
    return o


# pinned on the front-right of the beret's rounded edge, facing you, sitting ON the surface
# (lifted a little so nothing pokes through): two clean leaves fanned apart with a gold pin
_x, _y = 0.28, -0.68
_e = 0.01
_z = puff_z(_x, _y)
_dzdx = (puff_z(_x + _e, _y) - puff_z(_x - _e, _y)) / (2 * _e)
_dzdy = (puff_z(_x, _y + _e) - puff_z(_x, _y - _e)) / (2 * _e)
_nrm = Vector((-_dzdx, -_dzdy, 1.0)).normalized()
PIN = local_empty("LeafPinFrame", TOP, tuple(Vector((_x, _y, _z)) + _nrm * 0.035))
PIN.rotation_euler = _nrm.to_track_quat("Z", "Y").to_euler()
for k, (mat, ang, ln, wd) in enumerate(((leaf_orange, -38, 0.24, 0.075), (leaf_red, 36, 0.2, 0.065))):
    fr = local_empty("Leaf%d" % k, PIN, (0, 0, 0.012 * k), (0, 0, math.radians(ang)))
    OUTFITS["beret"].append(hat_part(leaf_mesh("Leaf%d" % k, ln, wd, 0.016), mat, fr, (0, ln * 0.5, 0)))
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.005, depth=ln * 0.8)    # the vein
    OUTFITS["beret"].append(hat_part(made(), leaf_vein, fr, (0, ln * 0.5, 0.018), (math.radians(90), 0, 0)))
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.036)
o = made()
o.scale = (1, 1, 0.6)
OUTFITS["beret"].append(hat_part(o, gold_pin, PIN, (0, 0, 0.03)))               # the pin

# bunny ears: the left one stands up, the right one folds over to the side near the top
bunny_white = outfit_mat("of_bunny", "#fbf8ff", 0.8)
for sx, lean in ((-1, 12), (1, 16)):
    ang = math.radians(16) * sx
    r = 0.5
    root = empty("BunnyEar%d" % sx, (r * math.sin(ang), 0.02, 2.015 + r * math.cos(ang)), HEAD)
    root.rotation_euler = (0, math.radians(lean) * sx, 0)
    if sx < 0:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
        o = made()
        o.scale = (0.14, 0.07, 0.43)
        OUTFITS["bunny"].append(hat_part(o, bunny_white, root, (0, 0, 0.36)))
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
        o = made()
        o.scale = (0.075, 0.03, 0.3)
        OUTFITS["bunny"].append(hat_part(o, ear_in, root, (0, -0.05, 0.38)))
        continue
    # lower half of the folding ear
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
    o = made()
    o.scale = (0.14, 0.07, 0.3)
    OUTFITS["bunny"].append(hat_part(o, bunny_white, root, (0, 0, 0.28)))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
    o = made()
    o.scale = (0.075, 0.03, 0.2)
    OUTFITS["bunny"].append(hat_part(o, ear_in, root, (0, -0.05, 0.3)))
    # the fold: a soft round knuckle, then the top half bending over outward and down a bit
    hinge = local_empty("BunnyHinge", root, (0, 0, 0.5), (0, math.radians(72), 0))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
    o = made()
    o.scale = (0.135, 0.068, 0.11)
    OUTFITS["bunny"].append(hat_part(o, bunny_white, hinge, (0, 0, 0)))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
    o = made()
    o.scale = (0.13, 0.065, 0.2)
    OUTFITS["bunny"].append(hat_part(o, bunny_white, hinge, (0, 0, 0.16)))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
    o = made()
    o.scale = (0.065, 0.028, 0.13)
    OUTFITS["bunny"].append(hat_part(o, ear_in, hinge, (0, -0.045, 0.18)))

# round glasses: two gold rims over her eyes and a little bridge
gold = outfit_mat("of_gold", "#e3b64e", 0.35)


for sx in (-1, 1):
    x, z = 0.26 * sx, EYE_Z
    y = -math.sqrt(max(0.0001, HEAD_R ** 2 - x ** 2 - z ** 2))
    pos = Vector((x, y - 0.075, HEAD_C.z + z + 0.005))
    nrm = (pos - HEAD_C).normalized()
    fr = empty("GlassRim%d" % sx, tuple(pos), HEAD)
    fr.rotation_euler = nrm.to_track_quat("Z", "Y").to_euler()
    bpy.ops.mesh.primitive_torus_add(major_radius=0.135, minor_radius=0.017, major_segments=64,
                                     minor_segments=12)
    OUTFITS["glasses"].append(hat_part(made(), gold, fr, (0, 0, 0)))
    # the arm going back toward her ear (mostly hidden by her hair)
    a = Vector((0.4 * sx, -0.43, HEAD_C.z + z + 0.02))
    b = Vector((0.56 * sx, -0.05, HEAD_C.z + z + 0.06))
    OUTFITS["glasses"].append(rod(tuple(a), tuple(b), 0.014, gold, HEAD))
OUTFITS["glasses"].append(rod((-0.13, -0.58, HEAD_C.z + EYE_Z + 0.03),
                                (0.13, -0.58, HEAD_C.z + EYE_Z + 0.03), 0.014, gold, HEAD))

# big hair bow on the top-left of her head
bow_pink = outfit_mat("of_bow", "#f27fa8", 0.55)
BOW = empty("BowFrame", tuple(HEAD_C + Vector((0, -0.28, 0.96)).normalized() * 0.62), HEAD)
BOW.rotation_euler = Vector((0, -0.75, 0.66)).normalized().to_track_quat("Z", "Y").to_euler()   # faces you
for sx in (-1, 1):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
    o = made()
    o.scale = (0.27, 0.17, 0.08)
    OUTFITS["bow"].append(hat_part(o, bow_pink, BOW, (0.23 * sx, 0, 0.09),
                                   (0, math.radians(-14 * sx), math.radians(10 * sx))))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1)
    o = made()
    o.scale = (0.08, 0.2, 0.04)
    OUTFITS["bow"].append(hat_part(o, bow_pink, BOW, (0.12 * sx, -0.2, 0.05),
                                   (0, 0, math.radians(22 * sx))))
bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=10, radius=0.09)
o = made()
o.scale = (1, 1, 0.75)
OUTFITS["bow"].append(hat_part(o, bow_pink, BOW, (0, 0, 0.12)))


# star clip on the right side, above her ear
def star_mesh(name, r_out, r_in, thick):
    import bmesh
    bm = bmesh.new()
    vs = []
    for k in range(10):
        a = math.pi / 2 + k * math.pi / 5
        r = r_out if k % 2 == 0 else r_in
        vs.append(bm.verts.new((r * math.cos(a), r * math.sin(a), 0)))
    f = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    moved = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, thick), verts=moved)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bv = o.modifiers.new("Puffy", "BEVEL")
    bv.width = thick * 0.4
    bv.segments = 4
    bv.limit_method = "NONE"
    return o


STAR = on_head((0.62, -0.42, 0.45), 0.6, "StarClipFrame")
OUTFITS["star"].append(hat_part(star_mesh("StarClip", 0.2, 0.085, 0.06), yolk, STAR, (0, 0, 0)))


# mittens that grip a window's edge while she peeks (not attached to her arms:
# the window hides her arms)
def grip(x, z):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.1, location=(x, -0.66, z))
    o = made()
    o.scale = (0.8, 0.6, 1.1)
    o.data.materials.append(blue_mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    o.hide_render = True
    return o


SIDE_EDGE = -0.2      # x of the window edge in the side-peek frames
TOP_EDGE = 1.72       # z of the window edge in the top-peek frames
GRIPS = {"side": [grip(SIDE_EDGE, 1.98), grip(SIDE_EDGE, 1.52)],
         "top": [grip(-0.32, TOP_EDGE), grip(0.32, TOP_EDGE)]}
PEEK_HIDDEN = []


def under(o, anc):
    while o.parent is not None:
        if o.parent == anc:
            return True
        o = o.parent
    return False


def peek_setup(kind):
    """Only her head (and the mittens on the edge) show: the window hides the rest."""
    for o in scene.objects:
        if o.type in ("MESH", "CURVE") and not o.hide_render and not under(o, HEAD):
            o.hide_render = True
            PEEK_HIDDEN.append(o)
    for g in GRIPS[kind]:
        g.hide_render = False


def shoot_hands(state, i, kind):
    """A second picture with only the mittens, drawn on top of the window."""
    if CURRENT_OUTFIT is not None:
        return
    keep = []
    for o in scene.objects:
        if o.type in ("MESH", "CURVE") and not o.hide_render and o not in GRIPS[kind]:
            o.hide_render = True
            keep.append(o)
    shoot(state, i)
    for o in keep:
        o.hide_render = False


# ------------------------------------------------------------- props for new poses
def obj_part(o, mat, parent=None, smooth=True):
    o.data.materials.append(mat)
    if smooth:
        for poly in o.data.polygons:
            poly.use_smooth = True
    o.hide_render = True
    if parent is not None:
        set_parent(o, parent)
    return o


def stick(a, b, radius, mat, parent=None):
    """A thin cylinder from point a to point b."""
    a, b = Vector(a), Vector(b)
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius, depth=d.length,
                                        location=(a + b) / 2)
    o = made()
    o.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    return obj_part(o, mat, parent)


gray_l = bpy.data.materials.get("gray_light") or white
gray_d = bpy.data.materials.get("gray_dark") or dock_gray
blk_m = bpy.data.materials.get("black") or witch
canopy = prop_mat("umbrella", "#f2a7c3", 0.6, stripes="#fff3f7")
ball_m = prop_mat("hugball", "#ffd54f", 0.5, stripes="#f27fa8")
key_m = prop_mat("keys", "#f4f4fa", 0.6)
PROPS2 = {}

# robot teddy bear she hugs (character space, she's sitting so ROOT carries it down)
t = []
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.21, location=(0, -0.44, 1.1))
t.append(obj_part(made(), blue_mat, ROOT))
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.16, location=(0, -0.5, 1.36))
t.append(obj_part(made(), gray_l, ROOT))
for sx in (-1, 1):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.06, location=(0.11 * sx, -0.48, 1.5))
    t.append(obj_part(made(), blue_mat, ROOT))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.025, location=(0.055 * sx, -0.645, 1.38))
    t.append(obj_part(made(), blk_m, ROOT))
t.append(stick((0, -0.5, 1.5), (0, -0.5, 1.6), 0.012, gray_d, ROOT))
bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.035, location=(0, -0.5, 1.62))
t.append(obj_part(made(), dock_glow, ROOT))
PROPS2["teddy"] = t

# a big two-tone ball to cuddle
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.27, location=(0, -0.46, 1.16))
PROPS2["ball"] = [obj_part(made(), ball_m, ROOT)]

# little keyboard on her lap
k = []
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.5, 0.74), rotation=(math.radians(12), 0, 0))
o = made()
o.scale = (0.62, 0.24, 0.04)
k.append(obj_part(o, gray_d, ROOT, smooth=False))
for row in range(3):
    for col in range(9):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(-0.24 + col * 0.06, -0.57 + row * 0.065,
                                                          0.77 + row * 0.014),
                                        rotation=(math.radians(12), 0, 0))
        o = made()
        o.scale = (0.045, 0.045, 0.02)
        k.append(obj_part(o, key_m, ROOT, smooth=False))
PROPS2["keyboard"] = k

# camera held up in front of her face
c = []
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.66, 1.76))
o = made()
o.scale = (0.36, 0.14, 0.22)
bv = o.modifiers.new("Soft", "BEVEL")
bv.width = 0.03
bv.segments = 3
c.append(obj_part(o, pink, ROOT))
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.075, depth=0.1, location=(0, -0.76, 1.75),
                                    rotation=(math.pi / 2, 0, 0))
c.append(obj_part(made(), blk_m, ROOT))
bpy.ops.mesh.primitive_cube_add(size=1, location=(0.11, -0.66, 1.9))
o = made()
o.scale = (0.08, 0.06, 0.05)
c.append(obj_part(o, white, ROOT, smooth=False))
PROPS2["camera"] = c

# zafu: a round, puffy meditation cushion with pleated sides, sitting on the floor under her
def pleat_mat(name, hexcol, pleat_hex, rough=0.75):
    m = prop_mat(name, hexcol, rough)
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    h1, h2 = hexcol.lstrip("#"), pleat_hex.lstrip("#")
    lin = lambda h: [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
                     for c in (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))]
    c1, c2 = lin(h1), lin(h2)
    wv = nt.nodes.new("ShaderNodeTexWave")          # soft vertical pleats all the way round
    wv.wave_type = "BANDS"
    wv.bands_direction = "X"
    wv.wave_profile = "SIN"
    wv.inputs["Scale"].default_value = 9.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (c2[0], c2[1], c2[2], 1)
    ramp.color_ramp.elements[1].color = (c1[0], c1[1], c1[2], 1)
    ramp.color_ramp.elements[1].position = 0.6
    nt.links.new(wv.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    nt.links.new(wv.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


zafu_side = pleat_mat("zafu_side", "#6c5aa8", "#5a4a92")
zafu_top = prop_mat("zafu_top", "#7a68b6", 0.8)
zafu_btn = prop_mat("zafu_button", "#f2c86b", 0.5)
z = []
bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.66, depth=0.3, location=(0, 0.06, 0.15))
o = made()
bv = o.modifiers.new("Soft", "BEVEL")
bv.width = 0.09
bv.segments = 8
z.append(obj_part(o, zafu_side, None))
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=24, radius=1, location=(0, 0.06, 0.29))
o = made()
o.scale = (0.63, 0.63, 0.12)                        # the puffy top
z.append(obj_part(o, zafu_top, None))
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.04, location=(0, -0.58, 0.2))
z.append(obj_part(made(), zafu_btn, None))           # the little button peeking out in front
PROPS2["zafu"] = z

# umbrella in her right hand: a half-dome canopy with ribs and a scalloped rim,
# held out to her right so the pole isn't hidden behind her head
def half_dome(radius, height, center, mat):
    import bmesh
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=radius, location=center)
    o = made()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.001], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    o.scale = (1, 1, height / radius)
    sol = o.modifiers.new("Thick", "SOLIDIFY")
    sol.thickness = 0.03
    return obj_part(o, mat, ROOT)


U_TOP = Vector((0.5, -0.55, 2.68))      # held well in front of her face       # middle of the canopy's rim
u = []
u.append(stick((0.46, -0.55, 1.45), U_TOP + Vector((0, 0, 0.5)), 0.022, gray_d, ROOT))
u.append(half_dome(0.78, 0.48, tuple(U_TOP), canopy))
# ribs along the canopy's 16 folds, and little tips on the rim
for k in range(16):
    a = 2 * math.pi * k / 16
    rim = U_TOP + Vector((0.78 * math.cos(a), 0.78 * math.sin(a), 0.0))
    if math.sin(a) < 0.2:                # only the ones you can see from the front
        bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=0.03, location=tuple(rim))
        u.append(obj_part(made(), gray_d, ROOT))
bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.045,
                                     location=tuple(U_TOP + Vector((0, 0, 0.52))))
u.append(obj_part(made(), gray_d, ROOT))
# curved J handle under her hand
bpy.ops.mesh.primitive_torus_add(major_radius=0.07, minor_radius=0.018, location=(0.42, -0.55, 1.43),
                                 rotation=(math.pi / 2, 0, 0))
u.append(obj_part(made(), gray_d, ROOT))
PROPS2["umbrella"] = u

# ------------------------------------------------------------- bottoms: skirt or shorts
SKIRT = [o for o in scene.objects if o.name.startswith("Skirt")]
SHORTS = []
# Nancy's design: wide, flared shorts (like culottes) - the same A-line as the skirt, split into
# two legs with a seam down the middle. Each leg is a slightly tilted open flared tube; the two
# overlap at the top and part at the hem, which makes the little notch in the middle.
for sx in (-1, 1):
    tilt_r = math.radians(10)
    bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.225, radius2=0.145, depth=0.37,
                                    end_fill_type="NOTHING",
                                    location=(0.1 * sx, 0, 0.845), rotation=(0, -sx * tilt_r, 0))
    o = made()
    o.name = "ShortsLeg%d" % sx
    # rounded hem like Nancy's drawing: each leg dips a little in the front middle,
    # and rises toward the split between the legs
    for v in o.data.vertices:
        if v.co.z < 0:
            front = max(0.0, -v.co.y / 0.225) ** 1.5
            inner = max(0.0, -sx * v.co.x / 0.225) ** 2
            v.co.z += -0.04 * front + 0.05 * inner
    sol = o.modifiers.new("Thickness", "SOLIDIFY")
    sol.thickness = 0.018
    bv = o.modifiers.new("Soft", "BEVEL")
    bv.width = 0.006
    bv.segments = 2
    SHORTS.append(obj_part(o, gray_d, ROOT))
# the seam down the front, from the belt to the split between the legs
SHORTS.append(stick((0, -0.135, 1.0), (0, -0.17, 0.69), 0.008,
                    bpy.data.materials.get("black") or gray_l, ROOT))
for o in SHORTS:
    o.name = o.name if o.name.startswith("Shorts") else "ShortsSeam"
BOTTOMS = {"skirt": SKIRT, "shorts": SHORTS}

# ------------------------------------------------------------- hair styles
# Every style is its own set of objects. Frames are rendered with no hair at all, and each style
# is rendered as a separate layer the app puts on top (so styles can be swapped and recolored).
import bmesh

HAIR_PURPLE = bpy.data.materials.get("hair")


def hair_color_mat(name, hexcol, rough=None):
    m = HAIR_PURPLE.copy() if HAIR_PURPLE is not None else bpy.data.materials.new(name)
    m.name = name
    m.use_nodes = True
    h = hexcol.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb]
    b = m.node_tree.nodes.get("Principled BSDF")
    if b is not None:
        bc = b.inputs["Base Color"]
        for lk in list(bc.links):
            m.node_tree.links.remove(lk)
        bc.default_value = (lin[0], lin[1], lin[2], 1)
        if rough is not None:
            b.inputs["Roughness"].default_value = rough
            for key in ("Specular IOR Level", "Specular"):
                if key in b.inputs:
                    b.inputs[key].default_value = 0.25
                    break
    return m


HAIR_NAVY = hair_color_mat("hair_navy", "#1f2a4c", rough=0.55)   # soft matte, like vinyl toys
HP = HAIR_PURPLE or HAIR_NAVY


def soft(o, thick=0.0, bevel=0.0):
    if thick:
        sol = o.modifiers.new("Thickness", "SOLIDIFY")
        sol.thickness = thick
    if bevel:
        bv = o.modifiers.new("Soft", "BEVEL")
        bv.width = bevel
        bv.segments = 2
    return o


def ribbon(name, P0, P1, P2, W, prof, th=0.12, mat=None, parent=None, steps=24, ring=16):
    """A tapered lock of hair along a curve (flat-ish, like her twin tails)."""
    P0, P1, P2 = Vector(P0), Vector(P1), Vector(P2)
    bm = bmesh.new()
    rings = []
    for i in range(steps + 1):
        t = i / steps
        c = (1 - t) ** 2 * P0 + 2 * (1 - t) * t * P1 + t ** 2 * P2
        d = 2 * (1 - t) * (P1 - P0) + 2 * t * (P2 - P1)
        d.normalize()
        n = Vector((-d.z, 0, d.x))
        if n.length < 1e-4:
            n = Vector((1, 0, 0))
        n.normalize()
        w = max(0.004, W * prof(t))
        thk = 0.012 + th * (w / W)
        verts = []
        for k in range(ring):
            a = 2 * math.pi * k / ring
            verts.append(bm.verts.new(c + n * (w * math.cos(a)) + Vector((0, 1, 0)) * (thk * math.sin(a))))
        rings.append(verts)
    for i in range(steps):
        for k in range(ring):
            k2 = (k + 1) % ring
            bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return obj_part(o, mat or HP, parent)


def lerp_pts(pts, x):
    """Piecewise-linear lookup in a list of (x, value) points."""
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, v0), (x1, v1) in zip(pts, pts[1:]):
        if x <= x1:
            return v0 + (v1 - v0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def shell(name, edge, xw=0.43, low=-0.5, grow=0.02, mat=None, segs=160, rows=28):
    """Hair hugging her head with a smooth edge around the visor. edge(x) = how low the bangs come."""
    R = HEAD_R + grow

    def cut(x, y, z):
        return (y < -0.1 and abs(x) < xw and z < edge(x)) or z < low

    bm = bmesh.new()
    pole = bm.verts.new((0, 0, R))
    cols = []
    for k in range(segs):
        az = 2 * math.pi * k / segs
        sa, ca = math.sin(az), -math.cos(az)
        # walk down this line of longitude until the hair should stop
        pb, steps = math.pi, 600
        for i in range(1, steps + 1):
            pp = math.pi * i / steps
            rho, z = R * math.sin(pp), R * math.cos(pp)
            if cut(rho * sa, rho * ca, z):
                lo, hi = math.pi * (i - 1) / steps, pp
                for _ in range(12):
                    mid = (lo + hi) / 2
                    rr, zz = R * math.sin(mid), R * math.cos(mid)
                    if cut(rr * sa, rr * ca, zz):
                        hi = mid
                    else:
                        lo = mid
                pb = lo
                break
        col = []
        for v in range(1, rows + 1):
            pp = pb * v / rows
            rho, z = R * math.sin(pp), R * math.cos(pp)
            col.append(bm.verts.new((rho * sa, rho * ca, z)))
        cols.append(col)
    for k in range(segs):
        k2 = (k + 1) % segs
        bm.faces.new((pole, cols[k][0], cols[k2][0]))
        for v in range(rows - 1):
            bm.faces.new((cols[k][v], cols[k2][v], cols[k2][v + 1], cols[k][v + 1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = HEAD_C
    bpy.context.collection.objects.link(o)
    return obj_part(o, mat or HP, HEAD)


def helmet(name, edge, z_bot, flare=0.10, xw=0.43, grow=0.05, mat=None, segs=240, rows=80, curl=0.0,
           extra=None, thick=0.03):
    """A smooth helmet of hair: hugs her head on top, keeps going down past her ears and flares out
    a little at the ends. edge(x) = where the bangs stop over the visor, z_bot(angle) = where the
    hair ends all around (angle 0 = front)."""
    R = HEAD_R + grow
    zmin = -0.8

    def rho(z, azd=0.0):
        base = 0.0
        if extra is not None:
            base = extra(z, azd)
        if z >= 0:
            return math.sqrt(max(0.0, R * R - z * z)) + base
        k = min(1.0, -z / 0.7)
        # flare: ends swing out; curl: the bob bulges a little then tucks back in toward her jaw
        return R + flare * k ** 1.6 + curl * math.sin(math.pi * k) - curl * 1.4 * k ** 3 + base

    def cut(x, y, z, az):
        return (y < -0.1 and abs(x) < xw and z < edge(x)) or z < z_bot(az)

    bm = bmesh.new()
    pole = bm.verts.new((0, 0, R))
    cols = []
    for k in range(segs):
        az = 2 * math.pi * k / segs
        sa, ca = math.sin(az), -math.cos(az)
        azd = math.degrees(az)
        azd = azd - 360 if azd > 180 else azd
        # walk down from the crown until the hair should stop
        zs = [R - (R - zmin) * i / 800 for i in range(1, 801)]
        zb = zmin
        prev = R
        for z in zs:
            r = rho(z, azd)
            if cut(r * sa, r * ca, z, azd):
                lo, hi = z, prev
                for _ in range(12):
                    mid = (lo + hi) / 2
                    rm = rho(mid, azd)
                    if cut(rm * sa, rm * ca, mid, azd):
                        lo = mid
                    else:
                        hi = mid
                zb = hi
                break
            prev = z
        # rings at the same heights all the way around (so a sudden change in length between
        # neighbors can't skew the whole column and leave a crease line up to the crown);
        # rings below where this column ends just collapse onto its edge
        col = []
        for v in range(1, rows + 1):
            z = max(zb, R - (R - zmin) * v / rows)
            r = rho(z, azd)
            col.append(bm.verts.new((r * sa, r * ca, z)))
        cols.append(col)
    for k in range(segs):
        k2 = (k + 1) % segs
        bm.faces.new((pole, cols[k][0], cols[k2][0]))
        for v in range(rows - 1):
            bm.faces.new((cols[k][v], cols[k2][v], cols[k2][v + 1], cols[k][v + 1]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = HEAD_C
    bpy.context.collection.objects.link(o)
    soft(o, thick=thick)
    return obj_part(o, mat or HP, HEAD)


def lock(name, az_deg, pts, W, prof, th=0.05, mat=None, parent=None, steps=20, ring=16, twist=0.0):
    """A lock of hair lying around her head: pts are (distance out from the middle, height)
    around the head at angle az_deg (0 = front, 90 = her left side seen from us = +x).
    Its width runs around the head, its thickness outward."""
    az = math.radians(az_deg)
    rad = Vector((math.sin(az), -math.cos(az), 0))
    tan = Vector((math.cos(az), math.sin(az), 0))
    P = [HEAD_C + rad * r + Vector((0, 0, z)) for r, z in pts]
    P0, P1, P2 = P
    bm = bmesh.new()
    rings = []
    for i in range(steps + 1):
        t = i / steps
        c = (1 - t) ** 2 * P0 + 2 * (1 - t) * t * P1 + t ** 2 * P2
        d = 2 * (1 - t) * (P1 - P0) + 2 * t * (P2 - P1)
        d.normalize()
        n = d.cross(tan)
        n.normalize()
        # twist turns the lock a little so it shows more of its width from the front
        tw = math.radians(twist)
        wd = tan * math.cos(tw) + n * math.sin(tw)
        nd = n * math.cos(tw) - tan * math.sin(tw)
        w = max(0.004, W * prof(t))
        thk = 0.01 + th * (w / W)
        verts = []
        for k in range(ring):
            a = 2 * math.pi * k / ring
            verts.append(bm.verts.new(c + wd * (w * math.cos(a)) + nd * (thk * math.sin(a))))
        rings.append(verts)
    for i in range(steps):
        for k in range(ring):
            k2 = (k + 1) % ring
            bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return obj_part(o, mat or HP, parent or HEAD)


def bell(name, z_top, z_bot, radius, cut_x, mat=None, rows=16, segs=96, thick=0.02):
    """A layer of hair hanging around her head (open at the bottom and at the face).
    z_bot(angle) = where the ends are (jagged strands), radius(z) = how far out it flares."""
    bm = bmesh.new()
    grid = []
    for j in range(rows + 1):
        u = j / rows
        row = []
        for k in range(segs):
            th = 2 * math.pi * k / segs
            z = z_top + (z_bot(th) - z_top) * u
            r = radius(z)
            row.append(bm.verts.new((r * math.sin(th), -r * math.cos(th), z)))
        grid.append(row)
    for j in range(rows):
        for k in range(segs):
            k2 = (k + 1) % segs
            a, b, c, d = grid[j][k], grid[j][k2], grid[j + 1][k2], grid[j + 1][k]
            ctr = (a.co + b.co + c.co + d.co) / 4
            if ctr.y < 0 and abs(ctr.x) < cut_x:
                continue
            bm.faces.new((a, b, c, d))
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = HEAD_C
    bpy.context.collection.objects.link(o)
    soft(o, thick)
    return obj_part(o, mat or HP, HEAD)


def curl_lock(name, az_deg, pts, W, prof, th=0.12, mat=None, parent=None, twist=0.0, steps=40, ring=18):
    """Like lock(), but follows any number of points smoothly, so it can curl at the end."""
    az = math.radians(az_deg)
    rad = Vector((math.sin(az), -math.cos(az), 0))
    tan = Vector((math.cos(az), math.sin(az), 0))
    P = [HEAD_C + rad * r + Vector((0, 0, z)) for r, z in pts]
    P = [P[0]] + P + [P[-1]]
    nseg = len(P) - 3

    def at(t):
        u = min(nseg - 1e-6, t * nseg)
        i = int(u)
        f = u - i
        p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
        return 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f
                      + (-p0 + 3 * p1 - 3 * p2 + p3) * f * f * f)

    tw = math.radians(twist)
    bm = bmesh.new()
    rings = []
    for i in range(steps + 1):
        t = i / steps
        c = at(t)
        d = at(min(1.0, t + 0.01)) - at(max(0.0, t - 0.01))
        d.normalize()
        n = d.cross(tan)
        n.normalize()
        wd = tan * math.cos(tw) + n * math.sin(tw)
        nd = n * math.cos(tw) - tan * math.sin(tw)
        w = max(0.006, W * prof(t))
        thk = max(0.006, th * prof(t))
        verts = []
        for k in range(ring):
            a = 2 * math.pi * k / ring
            verts.append(bm.verts.new(c + wd * (w * math.cos(a)) + nd * (thk * math.sin(a))))
        rings.append(verts)
    for i in range(steps):
        for k in range(ring):
            k2 = (k + 1) % ring
            bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return obj_part(o, mat or HP, parent or HEAD)


def round_tip(t):
    """full width almost all the way, then a rounded end (no sharp points)"""
    return max(0.0, 1 - t ** 5) ** 0.5


def tail_prof(t):
    return math.sin(math.pi * (0.12 + 0.88 * t) ** 0.85)


def H(x, z, y=0.0):
    """A point given relative to the middle of her head."""
    return (x, y, HEAD_C.z + z)


HAIRSTYLES = {}
_orig = [o for o in scene.objects if o.type == "MESH" and (o.name == "Hair" or
                                                           (o.name.startswith("Tail") and "Pivot" not in o.name))]
_cap = [o for o in _orig if o.name == "Hair"]
HAIRSTYLES["twintails"] = _orig

# short twin tails: same bangs, tails only reach about her chin
st = list(_cap)
for s in (-1, 1):
    st.append(ribbon("ShortTail%d" % s, (0.5 * s, 0, 2.40), (1.0 * s, 0, 2.30), (0.70 * s, 0, 1.64),
                     0.23, tail_prof, 0.11, HP, TAIL[s]))
HAIRSTYLES["shorttails"] = st

# drill tails: same bangs, and a big spiral drill curl on each side (like Nancy's reference):
# a flat-topped curl that winds down in flared bands to a thin curly tip
def drill(name, side, top=2.42, bottom=1.10, axis_x=0.74, R0=0.27, bands=7, rows=260, segs=56):
    bm = bmesh.new()
    L = top - bottom
    grid = []
    for j in range(rows + 1):
        u = j / rows
        base = R0 * max(0.04, (1 - u) ** 0.85) * (0.92 + 0.08 * min(1.0, u / 0.05))
        row = []
        for k in range(segs):
            ph = 2 * math.pi * k / segs
            f = (u * bands - side * ph / (2 * math.pi)) % 1.0       # where we are inside a band
            r = base * (0.80 + 0.20 * f ** 0.8)                      # each band flares out at its bottom
            row.append(bm.verts.new((side * axis_x + r * math.cos(ph), r * math.sin(ph), top - L * u)))
        grid.append(row)
    for j in range(rows):
        for k in range(segs):
            k2 = (k + 1) % segs
            bm.faces.new((grid[j][k], grid[j][k2], grid[j + 1][k2], grid[j + 1][k]))
    cap = bm.verts.new((side * axis_x, 0, top + 0.02))
    tip = bm.verts.new((side * axis_x, 0, bottom - 0.03))
    for k in range(segs):
        k2 = (k + 1) % segs
        bm.faces.new((cap, grid[0][k2], grid[0][k]))
        bm.faces.new((tip, grid[rows][k], grid[rows][k2]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return obj_part(o, HP, TAIL[side])


dr = list(_cap)
for s in (-1, 1):
    dr.append(drill("Drill%d" % s, s))
    # a little curl flicking out at the very tip
    dr.append(ribbon("DrillCurl%d" % s, (0.74 * s, 0, 1.16), (0.80 * s, 0, 0.98), (0.92 * s, 0, 1.06),
                     0.035, lambda t: 1 - 0.8 * t, 0.02, HP, TAIL[s]))
HAIRSTYLES["drills"] = dr

# shaggy: ONE smooth piece, like a vinyl-toy / LEGO hair helmet. Rounded bangs across the front
# (a long one in the middle between her eyes), and the ends swoop out like bed head.
def shag_edge(x):
    """how low the bangs come over the visor: rounded points, all stopping above her eyes"""
    if abs(x) > 0.385:
        return -0.60                      # side pieces framing her face
    z = 0.06
    for cx, depth, wid in ((0.0, 0.18, 0.12), (-0.19, 0.12, 0.085), (0.19, 0.12, 0.085),
                           (-0.325, 0.11, 0.065), (0.325, 0.11, 0.065)):
        d = abs(x - cx)
        if d < wid:
            z = min(z, 0.06 - depth * math.cos(d / wid * math.pi / 2) ** 0.7)
    return z


SWOOPS = (58, 92, 124, 156, -58, -92, -124, -156, 180)


def swoop(azd):
    """1 at the middle of a swoop, falling to 0 between them"""
    best = 0.0
    for c in SWOOPS:
        d = (azd - c + 180) % 360 - 180
        best = max(best, math.exp(-(d / 11.0) ** 2))
    return best


def cheek(azd):
    """1 where the strands beside her face are, 0 elsewhere"""
    return math.exp(-((abs(azd) - 40.0) / 14.0) ** 2)


def shag_bottom(azd):
    a = abs(azd)
    base = -0.28 - 0.16 * min(1.0, a / 150.0) - 0.15 * swoop(azd)
    c = cheek(azd)
    return (1 - c) * base + c * -0.25        # the face strands are shorter


def shag_extra(z, azd):
    k = min(1.0, max(0.0, -z / 0.55))
    out = 0.20 * swoop(azd) * k ** 2.6                         # ends swoop outward
    groove = abs(math.cos(math.radians(azd) * 9)) ** 24        # soft sculpted grooves between sections
    out -= 0.014 * groove * min(1.0, max(0.0, (0.35 - z) / 0.35))
    # the strands beside her face curve in a little at the ends, cupping her cheeks
    kc = min(1.0, max(0.0, -z / 0.25))
    out -= 0.09 * cheek(azd) * kc ** 2
    return out


sh = [helmet("ShagHelmet", shag_edge, shag_bottom, flare=0.0, curl=0.035, extra=shag_extra,
             thick=0.045, mat=HAIR_NAVY)]
HAIRSTYLES["shaggy"] = sh


def shag_prof(t):
    return (1 - t ** 2.5) ** 0.6


# swept: same smooth one-piece "vinyl helmet" idea as shaggy, but shorter, with the bangs in one
# clean curved swoop from high on her left down over her right (stopping above her eye), bed-head
# swoops around the bottom, and two smooth horn tufts on top
def sweep_edge(x):
    if abs(x) > 0.43:
        return 0.2
    if x > 0.385:
        return -0.60                                    # piece beside her face on her right
    u = (x + 0.43) / 0.815
    z = 0.15 - 0.27 * (1 - (1 - u) ** 2)                # one smooth swoop down to the right
    tip = max(0.0, 1 - abs(x - 0.355) / 0.05)           # rounded point at the end of the swoop
    return z - 0.04 * math.sin(tip * math.pi / 2)


SWEEP_SWOOPS = (70, 104, 138, -70, -104, -138, 172, -172)


def sweep_swoop(azd):
    best = 0.0
    for c in SWEEP_SWOOPS:
        d = (azd - c + 180) % 360 - 180
        best = max(best, math.exp(-(d / 11.0) ** 2))
    return best


def sweep_bottom(azd):
    a = abs(azd)
    return -0.24 - 0.14 * min(1.0, a / 150.0) - 0.13 * sweep_swoop(azd)


def sweep_extra(z, azd):
    k = min(1.0, max(0.0, -z / 0.45))
    return 0.18 * sweep_swoop(azd) * k ** 2.4          # smooth, no grooves


sw = [helmet("SweptHelmet", sweep_edge, sweep_bottom, flare=0.0, curl=0.03,
             extra=sweep_extra, thick=0.045, mat=HAIR_NAVY, segs=320)]
for s_ in (-1, 1):
    # smooth horn tufts: rounder and thicker, growing out of the helmet
    sw.append(ribbon("SweptTuft%d" % s_, H(0.34 * s_, 0.34), H(0.60 * s_, 0.38), H(0.74 * s_, 0.52),
                     0.14, lambda t: (1 - t) ** 0.7, 0.10, HAIR_NAVY, HEAD, steps=48, ring=28))
HAIRSTYLES["swept"] = sw

ALL_HAIR = []
for objs in HAIRSTYLES.values():
    for o in objs:
        if o not in ALL_HAIR:
            ALL_HAIR.append(o)
for o in ALL_HAIR:
    o.hide_render = True
for o in _orig:          # the original hair stays visible unless we're making layers
    o.hide_render = False


ARM_REST = Vector((0.32, 0, -0.44))     # right hand relative to the right shoulder


def aim_arm(side, target):
    """Point an arm so its hand lands on `target` (character space)."""
    piv = Vector((0.20 * side, 0, 1.37))
    rest = Vector((ARM_REST.x * side, 0, ARM_REST.z))
    want = Vector(target) - piv
    ARM[side].rotation_mode = "QUATERNION"
    ARM[side].rotation_quaternion = rest.rotation_difference(want)
    sc = max(0.8, want.length / rest.length)
    ARM[side].scale = (sc, sc, sc)


def show2(name):
    for o in PROPS2[name]:
        o.hide_render = False


# ------------------------------------------------------------- render settings
scene.render.resolution_x = 440
scene.render.resolution_y = 480
scene.render.line_thickness = 1.3
vl = scene.view_layers[0]
if vl.freestyle_settings.linesets:
    ls = vl.freestyle_settings.linesets[0]
    if ls.linestyle is not None:
        ls.linestyle.thickness = 1.3
scene.cycles.samples = 24


# ------------------------------------------------------------- posing helpers
# hats that tuck her hair under them: any hair poking up through the hat gets pressed down just
# under it (only while that hat's frames render), so it looks like the hair is hiding under the hat
HAIR_TUCK = {"sunhat"}


def tuck_hair(hat_objs, depth=0.4, margin=0.03):
    from mathutils.bvhtree import BVHTree
    reset()
    update()
    deps = bpy.context.evaluated_depsgraph_get()
    hats = [(BVHTree.FromObject(h, deps), h.matrix_world.copy(), h.matrix_world.inverted()) for h in hat_objs
            if h.type == "MESH" and any(sl.material is not None and sl.material.name.startswith("of_straw")
                                        for sl in h.material_slots)]    # the hat itself, not its ribbons
    saved, seen = [], set()
    for objs in HAIRSTYLES.values():
        for o in objs:
            if o.type != "MESH" or o.name in seen:
                continue
            seen.add(o.name)
            me = bpy.data.meshes.new_from_object(o.evaluated_get(deps))   # modifiers baked in
            mw = o.matrix_world.copy()
            mwi = mw.inverted()
            moved = 0
            for v in me.vertices:
                p = mw @ v.co
                for tree, hw, hwi in hats:
                    q = hwi @ p
                    hit = tree.ray_cast(q, Vector((0, 0, -1)), depth)
                    if hit[0] is not None:          # the hat is right below: this bit pokes out
                        q2 = Vector((q.x, q.y, hit[0].z - margin))
                        p = hw @ q2
                        moved += 1
                v.co = mwi @ p
            if not moved:
                bpy.data.meshes.remove(me)
                continue
            mods = [(m, m.show_render, m.show_viewport) for m in o.modifiers]
            for m, _, _ in mods:
                m.show_render = m.show_viewport = False
            saved.append((o, o.data, me, mods))
            o.data = me
    update()
    return saved


def untuck_hair(saved):
    for o, data, me, mods in saved:
        o.data = data
        for m, r, v in mods:
            m.show_render, m.show_viewport = r, v
        bpy.data.meshes.remove(me)
    update()


def reset():
    ROOT.location = (0, 0, 0)
    ROOT.rotation_euler = (0, 0, 0)
    HEAD.rotation_euler = (0, 0, 0)
    for s in (-1, 1):
        ARM[s].rotation_euler = (0, 0, 0)
        ARM[s].scale = (1, 1, 1)
        ARM[s].rotation_mode = "XYZ"
        ARM[s].rotation_quaternion = (1, 0, 0, 0)
        LEG[s].location = (0.14 * s, 0, 0.68)
        LEG[s].rotation_euler = (0, 0, 0)
        TAIL[s].rotation_euler = (0, 0, 0)
    set_eyes("caret")
    set_blush(False)
    for o in HEADPHONES:
        o.hide_render = True
    for objs in PROPS.values():
        for o in objs:
            o.hide_render = True
    BLANKET.location.z = BLANKET_Z
    for o in PEEK_HIDDEN:
        o.hide_render = False
    PEEK_HIDDEN.clear()
    for objs in PROPS2.values():
        for o in objs:
            o.hide_render = True
    for gs in GRIPS.values():
        for g in gs:
            g.hide_render = True


def set_eyes(kind):
    for k, objs in EYES.items():
        for o in objs:
            o.hide_render = (k != kind)


def set_blush(on):
    for b in BLUSH:
        b.hide_render = not on


def arm_raise(side, deg):
    """Positive = arm lifts up and out to that side."""
    ARM[side].rotation_euler = (0, math.radians(-side * deg), 0)


def tilt(obj, deg):
    obj.rotation_euler = (0, math.radians(deg), 0)


def tails(deg_left, deg_right):
    tilt(TAIL[-1], deg_left)
    tilt(TAIL[1], deg_right)


# optional: only render some states, e.g.  ... -P animate_pet.py -- held
#   "outfits" also renders every state again wearing each 3D outfit
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUTFITS_MODE = "outfits" in ARGS
PREVIEW = "preview" in ARGS            # outfits: just one test picture each
ALL = "all" in ARGS                    # base pass: render every state
HAIR = "hair" in ARGS                  # also make a recolorable hair layer for each frame
# frames are always rendered without a skirt now, plus separate skirt/shorts layers the app puts
# on top (so you can swap them). Add "baked" to get the old all-in-one frames instead.
SPLIT_BOTTOMS = "baked" not in ARGS
ONLY = [a for a in ARGS if a not in ("outfits", "preview", "all", "hair", "bottoms", "baked",
                                     "santa", "witch", "ears", "flower", "scarf", "party", "heart",
                                     "sunhat", "beret", "bunny", "glasses", "bow", "star")
        and a not in HAIRSTYLES]
# hair styles are rendered as separate layers too (pick some by name, otherwise all of them)
LAYERED_HAIR = "baked" not in ARGS
STYLE_PICK = [a for a in ARGS if a in HAIRSTYLES] or list(HAIRSTYLES)
if PREVIEW:                     # test pictures go in their own folder, not into her real frames
    OUT_DIR = os.path.join(HERE, "preview_frames")
    os.makedirs(OUT_DIR, exist_ok=True)
CURRENT_OUTFIT = None          # set while rendering an outfit pass
PASS_CAM = "normal"


def set_cam(kind):
    """normal: the original 440x480 frames. tall: same size and floor, 100px more headroom."""
    cam = scene.camera
    if kind == "tall":
        scene.render.resolution_y = 580
        cam.data.ortho_scale = 2.9 * 580 / 480
        cam.location.z = (555 - 290) / (480 / 2.9)
    else:
        scene.render.resolution_y = 480
        cam.data.ortho_scale = 2.9
        cam.location.z = 1.3


def shoot(state, i):
    if PREVIEW and i != 0 and state != "turn":
        return
    if CURRENT_OUTFIT is None:
        if not ALL and (ONLY or OUTFITS_MODE) and state not in ONLY:
            return
        folder = OUT_DIR
    else:
        if state.endswith("_hands") or state.startswith("sleep_") or state == "umbrella":
            return
        if ONLY and state not in ONLY:
            return
        if PREVIEW and not (i == 0 and state in ("idle", "peekside", "peektop")):
            return
        folder = os.path.join(OUT_DIR, "outfit_" + CURRENT_OUTFIT)
        os.makedirs(folder, exist_ok=True)
    update()
    scene.render.filepath = os.path.join(folder, "%s_%02d.png" % (state, i))
    bpy.ops.render.render(write_still=True)
    print("frame ->", scene.render.filepath)
    fname = "%s_%02d.png" % (state, i)
    if LAYERED_HAIR and not state.endswith("_hands"):
        for sname in STYLE_PICK:
            d = os.path.join(folder, "hairstyle_" + sname)
            cutout_layer(HAIRSTYLES[sname], os.path.join(d, fname),
                         os.path.join(d, "gray", fname))
    elif HAIR and not state.endswith("_hands"):
        hair_layer(scene.render.filepath, os.path.join(folder, "hair", fname))
    if (SPLIT_BOTTOMS and CURRENT_OUTFIT is None and not state.endswith("_hands")
            and not state.startswith("peek")):     # peeking: the window hides her skirt
        for name in BOTTOMS:
            bottom_layer(name, os.path.join(folder, "bottom_" + name, "%s_%02d.png" % (state, i)))


def bottom_layer(name, out_path):
    cutout_layer(BOTTOMS[name], out_path)


def cutout_layer(shown, out_path, gray_path=None):
    """Just these objects (skirt, shorts or a hair style), cut out of a full render so the app can
    lay them over a frame rendered without them. Outlines hide properly behind things in front.
    gray_path: also save a gray copy the app can tint any color (for hair)."""
    import numpy as np
    global HAIR_MASK_MAT
    for o in shown:
        o.hide_render = False
    path0 = scene.render.filepath
    full_path = os.path.join(bpy.app.tempdir or "/tmp", "digi_layer_full.png")
    scene.render.filepath = full_path
    bpy.ops.render.render(write_still=True)
    # quick mask: these objects glow white, everything else just blocks them
    if HAIR_MASK_MAT is None:
        HAIR_MASK_MAT = bpy.data.materials.new("hairmask")
        HAIR_MASK_MAT.use_nodes = True
        nt = HAIR_MASK_MAT.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (1, 1, 1, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    is_hair = gray_path is not None
    swapped, held = [], []
    for o in scene.objects:
        if o.type not in ("MESH", "CURVE") or o.hide_render:
            continue
        slots = [sl for sl in o.material_slots if sl.material is not None]
        # cat-ear outfit is made of hair, so it recolors with her hair too
        mine = o in shown or (is_hair and any(sl.material.name.startswith("hair") for sl in slots))
        if mine:
            for sl in slots:
                swapped.append((sl, sl.material))
                sl.material = HAIR_MASK_MAT
        else:
            o.is_holdout = True
            held.append(o)
    fs, samples = scene.render.use_freestyle, scene.cycles.samples
    scene.render.use_freestyle = False
    scene.cycles.samples = 6
    mask_path = os.path.join(bpy.app.tempdir or "/tmp", "digi_layer_mask.png")
    scene.render.filepath = mask_path
    bpy.ops.render.render(write_still=True)
    scene.render.use_freestyle, scene.cycles.samples, scene.render.filepath = fs, samples, path0
    for sl, m in swapped:
        sl.material = m
    for o in held:
        o.is_holdout = False
    # one more quick mask, of the hat/accessory she's wearing: where it sits IN FRONT of her hair
    # (like a beret's band resting on it) there's no outline in the render, so we ink one in
    worn = [o for lst in OUTFITS.values() for o in lst
            if not o.hide_render and o.type in ("MESH", "CURVE") and o not in shown
            and not any(sl.material is not None and sl.material.name.startswith("hair")
                        for sl in o.material_slots)]          # cat ears ARE hair: leave them be
    worn_path = None
    if gray_path and worn:
        swapped2, held2 = [], []
        for o in scene.objects:
            if o.type not in ("MESH", "CURVE") or o.hide_render:
                continue
            if o in worn:
                for sl in o.material_slots:
                    if sl.material is not None:
                        swapped2.append((sl, sl.material))
                        sl.material = HAIR_MASK_MAT
            else:
                o.is_holdout = True
                held2.append(o)
        scene.render.use_freestyle = False
        scene.cycles.samples = 6
        worn_path = os.path.join(bpy.app.tempdir or "/tmp", "digi_layer_worn.png")
        scene.render.filepath = worn_path
        bpy.ops.render.render(write_still=True)
        scene.render.use_freestyle, scene.cycles.samples, scene.render.filepath = fs, samples, path0
        for sl, m in swapped2:
            sl.material = m
        for o in held2:
            o.is_holdout = False
    for o in shown:
        o.hide_render = True
    # cut it out: inside the mask, plus the dark outline pixels hugging its edge
    full = bpy.data.images.load(full_path, check_existing=False)
    mask = bpy.data.images.load(mask_path, check_existing=False)
    w, h = full.size
    fp = np.array(full.pixels[:], dtype=np.float32).reshape(h, w, 4)
    m = np.array(mask.pixels[:], dtype=np.float32).reshape(h, w, 4)[..., 3]
    extra = []
    if worn_path:
        wimg = bpy.data.images.load(worn_path, check_existing=False)
        extra.append(wimg)
        wm = np.array(wimg.pixels[:], dtype=np.float32).reshape(h, w, 4)[..., 3] > 0.5
        near = wm.copy()                       # the accessory, grown by one pixel (8 neighbors)
        near[1:, :] |= wm[:-1, :]
        near[:-1, :] |= wm[1:, :]
        near[:, 1:] |= wm[:, :-1]
        near[:, :-1] |= wm[:, 1:]
        near[1:, 1:] |= wm[:-1, :-1]
        near[:-1, :-1] |= wm[1:, 1:]
        near[1:, :-1] |= wm[:-1, 1:]
        near[:-1, 1:] |= wm[1:, :-1]
        seam = (m > 0.5) & ~wm & near          # hair pixels right against it: ink them
        fp[seam, 0:3] = (0.015, 0.012, 0.015)
    grow = m > 0.05
    for _ in range(3):
        g2 = grow.copy()
        g2[1:, :] |= grow[:-1, :]
        g2[:-1, :] |= grow[1:, :]
        g2[:, 1:] |= grow[:, :-1]
        g2[:, :-1] |= grow[:, 1:]
        grow = g2
    lum = 0.299 * fp[..., 0] + 0.587 * fp[..., 1] + 0.114 * fp[..., 2]
    edge = grow & (lum < 0.18)
    a = np.maximum(m, edge.astype(np.float32)) * fp[..., 3]
    keep = (a > 0).astype(np.float32)          # blank out the rest so the files stay small
    outs = [(out_path, np.dstack([fp[..., 0] * keep, fp[..., 1] * keep, fp[..., 2] * keep, a]))]
    if gray_path:
        inside = lum[(m > 0.6) & (fp[..., 3] > 0.5)]
        ref = float(np.median(inside)) if inside.size else 1.0
        g = np.clip(lum / max(ref, 1e-3) * 0.85, 0.0, 1.0) * keep
        outs.append((gray_path, np.dstack([g, g, g, a])))
    imgs = [full, mask] + extra
    for path, arr in outs:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = bpy.data.images.new("layer", w, h, alpha=True)
        img.pixels.foreach_set(arr.astype(np.float32).ravel())
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        imgs.append(img)
    for im in imgs:
        bpy.data.images.remove(im)


HAIR_MASK_MAT = None


def hair_layer(base_path, out_path):
    """A gray copy of just her hair (shading and outlines kept), so the app can recolor it."""
    import numpy as np
    global HAIR_MASK_MAT
    if HAIR_MASK_MAT is None:
        HAIR_MASK_MAT = bpy.data.materials.new("hairmask")
        HAIR_MASK_MAT.use_nodes = True
        nt = HAIR_MASK_MAT.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (1, 1, 1, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    # 1) a quick render where only hair shows: everything else just blocks it (holdout)
    swapped, held = [], []
    for o in scene.objects:
        if o.type not in ("MESH", "CURVE") or o.hide_render:
            continue
        slots = [sl for sl in o.material_slots if sl.material is not None]
        if any(sl.material.name == "hair" for sl in slots):
            for sl in slots:
                swapped.append((sl, sl.material))
                sl.material = HAIR_MASK_MAT
        else:
            o.is_holdout = True
            held.append(o)
    fs, samples, path0 = scene.render.use_freestyle, scene.cycles.samples, scene.render.filepath
    scene.render.use_freestyle = False
    scene.cycles.samples = 6
    mask_path = os.path.join(bpy.app.tempdir or "/tmp", "digi_hair_mask.png")
    scene.render.filepath = mask_path
    bpy.ops.render.render(write_still=True)
    scene.render.use_freestyle, scene.cycles.samples, scene.render.filepath = fs, samples, path0
    for sl, m in swapped:
        sl.material = m
    for o in held:
        o.is_holdout = False
    # 2) gray hair = brightness of the real frame inside the mask
    base = bpy.data.images.load(base_path, check_existing=False)
    mask = bpy.data.images.load(mask_path, check_existing=False)
    w, h = base.size
    bp = np.array(base.pixels[:], dtype=np.float32).reshape(h, w, 4)
    mp = np.array(mask.pixels[:], dtype=np.float32).reshape(h, w, 4)
    m = mp[..., 3] * bp[..., 3]
    lum = 0.299 * bp[..., 0] + 0.587 * bp[..., 1] + 0.114 * bp[..., 2]
    inside = lum[m > 0.6]
    ref = float(np.median(inside)) if inside.size else 1.0
    g = np.clip(lum / max(ref, 1e-3) * 0.85, 0.0, 1.0)
    outp = np.stack([g, g, g, m], axis=-1).astype(np.float32)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img = bpy.data.images.new("hairlayer", w, h, alpha=True)
    img.pixels.foreach_set(outp.ravel())
    img.filepath_raw = out_path
    img.file_format = "PNG"
    img.save()
    for im in (base, mask, img):
        bpy.data.images.remove(im)


def wave(i, n, phase=0.0):
    return math.sin(2 * math.pi * (i / n) + phase)


F = 8


if SPLIT_BOTTOMS:
    for objs in BOTTOMS.values():
        for o in objs:
            o.hide_render = True
if LAYERED_HAIR:
    for o in ALL_HAIR:
        o.hide_render = True


def render_states():
    # ------------------------------------------------------------- the states
    F = 8

    # turn: her standing turned 40 and 90 degrees (just for checking hair styles from the side)
    if "turn" in ARGS and CURRENT_OUTFIT is None:
        for i, ang in enumerate((40, 90)):
            reset()
            ROOT.rotation_euler = (0, 0, math.radians(ang))
            shoot("turn", i)

    # idle: gentle breathing bob, tails drift
    for i in range(F):
        reset()
        ROOT.location.z = 0.015 * wave(i, F)
        tails(3 * wave(i, F, 1.0), -3 * wave(i, F, 1.0))
        arm_raise(-1, 2 * wave(i, F))
        arm_raise(1, 2 * wave(i, F))
        shoot("idle", i)

    # blink: one frame, eyes closed
    reset()
    set_eyes("line")
    shoot("blink", 0)

    # happy: bouncing with arms up, blushing
    for i in range(F):
        reset()
        set_blush(True)
        hop = abs(wave(i, F))
        ROOT.location.z = 0.09 * hop
        arm_raise(-1, 45 + 20 * hop)
        arm_raise(1, 45 + 20 * hop)
        tails(-8 * hop, 8 * hop)
        shoot("happy", i)

    # sleepy: droopy head sway, closed curved eyes
    for i in range(F):
        reset()
        set_eyes("sleepy")
        ROOT.location.z = -0.02 + 0.01 * wave(i, F)
        tilt(HEAD, 10 + 4 * wave(i, F))
        tails(4 + 2 * wave(i, F), 4 + 2 * wave(i, F))
        arm_raise(-1, -3)
        arm_raise(1, -3)
        shoot("sleepy", i)

    # surprised: little hop, O O eyes, arms out
    for i, (hop, arms) in enumerate(((0.08, 35), (0.03, 25))):
        reset()
        set_eyes("circle")
        ROOT.location.z = hop
        arm_raise(-1, arms)
        arm_raise(1, arms)
        tails(-10, 10)
        shoot("surprised", i)

    # walk: front-facing waddle, feet lift in turn
    for i in range(F):
        reset()
        w = wave(i, F)
        ROOT.location.z = 0.025 * abs(w)
        ROOT.rotation_euler = (0, math.radians(4 * w), 0)
        LEG[-1].location.z = 0.68 + 0.07 * max(0.0, w)
        LEG[1].location.z = 0.68 + 0.07 * max(0.0, -w)
        arm_raise(-1, 8 + 10 * w)
        arm_raise(1, 8 - 10 * w)
        tails(-4 * w, -4 * w)
        shoot("walk", i)

    # sing: swaying side to side, happy eyes and blush
    for i in range(F):
        reset()
        set_blush(True)
        for o in HEADPHONES:
            o.hide_render = (CURRENT_OUTFIT or "").split("-")[0] in ("santa", "witch", "ears", "party",
                                                                           "sunhat", "beret", "bunny")
        w = wave(i, F)
        ROOT.rotation_euler = (0, math.radians(5 * w), 0)
        tilt(HEAD, 8 * w)
        ROOT.location.z = 0.02 * abs(w)
        arm_raise(-1, 20 + 15 * w)
        arm_raise(1, 20 - 15 * w)
        tails(6 * w, 6 * w)
        shoot("sing", i)

    # held: picked up by the head like a cat, everything goes limp and dangles
    for i in range(6):
        reset()
        set_eyes("line")
        w = wave(i, 6)
        arm_raise(-1, -28 + 4 * w)
        arm_raise(1, -28 - 4 * w)
        tilt(HEAD, 3 * w)
        for s in (-1, 1):
            LEG[s].location.z = 0.68 - 0.05                     # legs stretch down
            LEG[s].rotation_euler = (0, math.radians(-s * 4 + 7 * w * s), 0)
        tails(-6 + 3 * w, 6 + 3 * w)                            # tails droop inward
        shoot("held", i)

    # sit: perched on the top edge of a window, legs dangling and kicking
    for i in range(8):
        reset()
        w = wave(i, 8)
        for s in (-1, 1):
            kick = 65 + 22 * w * s                              # legs kick in turn
            LEG[s].rotation_euler = (math.radians(-kick), math.radians(-s * 5), 0)
        arm_raise(-1, 6)
        arm_raise(1, 6)
        tilt(HEAD, 3 * w)
        tails(2 * w, 2 * w)
        shoot("sit", i)

    # stretch: her robot arms telescope up into a big "Y" stretch, swaying side to side
    for i in range(8):
        reset()
        w = wave(i, 8)
        set_eyes("line")
        ROOT.rotation_euler = (0, math.radians(4 * w), 0)
        ROOT.location.z = 0.02 + 0.015 * abs(w)
        for s in (-1, 1):
            ARM[s].scale = (1.9, 1.9, 1.9)
            ARM[s].rotation_euler = (math.radians(-25), math.radians(-s * (108 + 6 * w * s)), 0)
        tilt(HEAD, -3 * w)
        tails(-4 * w, -4 * w)
        shoot("stretch", i)

    # sitfloor: sitting on the floor, legs out in front, little kicks
    for i in range(8):
        reset()
        w = wave(i, 8)
        ROOT.location = (0, 0, -0.46)
        for s in (-1, 1):
            LEG[s].rotation_euler = (math.radians(-(82 + 8 * w * s)), math.radians(-s * 8), 0)
        arm_raise(-1, -6)
        arm_raise(1, -6)
        tilt(HEAD, 3 * w)
        tails(2 * w, 2 * w)
        shoot("sitfloor", i)

    # meditate: kneeling on her zafu (legs tucked under, out of sight), hands resting on her lap,
    # eyes softly closed, breathing slowly (a gentle rise and fall)
    for i in range(8):
        reset()
        w = wave(i, 8)
        show2("zafu")
        set_eyes("sleepy")
        ROOT.location = (0, 0, -0.30 + 0.012 * w)          # sitting right on top of the cushion
        for s in (-1, 1):
            for o in LEG[s].children_recursive:             # legs tucked under her: hidden
                if not o.hide_render:
                    o.hide_render = True
                    PEEK_HIDDEN.append(o)                    # reset() brings them back
        aim_arm(1, (0.19, -0.36, 0.64 + 0.01 * w))
        aim_arm(-1, (-0.19, -0.36, 0.64 + 0.01 * w))
        tilt(HEAD, 1.5 * w)
        tails(1.5 * w, 1.5 * w)
        shoot("meditate", i)


    # shy: hands on her cheeks, eyes squeezed happy, blushing
    for i in range(4):
        reset()
        w = wave(i, 4)
        set_eyes("sleepy")
        set_blush(True)
        aim_arm(1, (0.29, -0.42, 1.72 + 0.02 * w))
        aim_arm(-1, (-0.29, -0.42, 1.72 - 0.02 * w))
        tilt(HEAD, 6 + 3 * w)
        ROOT.rotation_euler = (0, math.radians(2 * w), 0)
        shoot("shy", i)

    # scared: hands up, O O eyes, a little crouch
    for i in range(4):
        reset()
        w = wave(i, 4)
        set_eyes("circle")
        ROOT.location.z = -0.04
        aim_arm(1, (0.56, -0.28, 1.76 + 0.03 * w))
        aim_arm(-1, (-0.56, -0.28, 1.76 - 0.03 * w))
        tilt(HEAD, -4 * w)
        tails(-6, 6)
        shoot("scared", i)

    # shiver: hugging herself, eyes squeezed shut
    for i in range(4):
        reset()
        w = wave(i, 4)
        set_eyes("line")
        aim_arm(1, (-0.09, -0.34, 1.14))
        aim_arm(-1, (0.09, -0.36, 1.22))
        ROOT.location.x = 0.015 * w
        tilt(HEAD, 2 * w)
        shoot("shiver", i)

    # cuddle: sitting, hugging a robot teddy or a ball, sleepy and happy
    for prop in ("teddy", "ball"):
        for i in range(6):
            reset()
            w = wave(i, 6)
            show2(prop)
            set_eyes("sleepy")
            set_blush(True)
            ROOT.location = (0, 0, -0.46 + 0.006 * w)
            for s in (-1, 1):
                LEG[s].rotation_euler = (math.radians(-82), math.radians(-s * 8), 0)
            aim_arm(1, (0.2, -0.46, 1.18))
            aim_arm(-1, (-0.2, -0.46, 1.14))
            tilt(HEAD, 10 + 2 * w)
            shoot("cuddle_" + prop, i)

    # typing: sitting with a little keyboard on her lap, hands tapping in turn
    for i in range(6):
        reset()
        w = wave(i, 6)
        show2("keyboard")
        ROOT.location = (0, 0, -0.46)
        for s in (-1, 1):
            LEG[s].rotation_euler = (math.radians(-82), math.radians(-s * 8), 0)
        aim_arm(1, (0.17, -0.5, 0.82 + 0.04 * max(0.0, w)))
        aim_arm(-1, (-0.17, -0.5, 0.82 + 0.04 * max(0.0, -w)))
        tilt(HEAD, 2 * w)
        shoot("typing", i)

    # camera: holding a camera up to her face
    for i in range(2):
        reset()
        show2("camera")
        aim_arm(1, (0.2, -0.62, 1.74))
        aim_arm(-1, (-0.2, -0.62, 1.74))
        tilt(HEAD, 3 * i)
        shoot("camera", i)

    # umbrella: holding it up over her head in the rain (needs the tall frame for the canopy)
    set_cam("tall")
    for i in range(6):
        reset()
        w = wave(i, 6)
        show2("umbrella")
        aim_arm(1, (0.46, -0.55, 1.58))
        arm_raise(-1, 4 * w)
        ROOT.location.z = 0.01 * w
        tails(2 * w, 2 * w)
        shoot("umbrella", i)
    set_cam(PASS_CAM)

    # peekside: peeking out past a window's side edge, one eye showing, mittens on the edge
    set_cam("tall")
    for i in range(4):
        reset()
        w = wave(i, 4)
        ROOT.location.x = -0.38
        tilt(HEAD, 28 + 3 * w)
        tails(-3 * w, 6 + 3 * w)
        peek_setup("side")
        shoot("peekside", i)
        shoot_hands("peekside_hands", i, "side")

    # peektop: peeking over a window's top edge
    for i in range(4):
        reset()
        w = wave(i, 4)
        tilt(HEAD, 4 * w)
        tails(2 * w, 2 * w)
        peek_setup("top")
        shoot("peektop", i)
        shoot_hands("peektop_hands", i, "top")
    reset()
    set_cam(PASS_CAM)


render_states()

# ------------------------------------------------------------- nap time in bed
# a wider camera so she fits lying down; the floor stays at the same height in the frame
cam = scene.camera
old_cam = (cam.location.z, cam.data.ortho_scale)
cam.location.z = 1.61
cam.data.ortho_scale = 3.6


def show(kind):
    for o in PROPS[kind]:
        o.hide_render = False


# A. futon: lying on her side under a striped blanket, head on the pillow
for i in range(8):
    reset()
    show("futon")
    w = wave(i, 8)
    set_eyes("sleepy")
    ROOT.rotation_euler = (0, math.radians(90), 0)
    ROOT.location = (-1.2, 0, 0.55 + 0.008 * w)
    tilt(HEAD, -70)
    arm_raise(-1, -20)
    arm_raise(1, -20)
    tails(-15, 25)
    BLANKET.location.z = BLANKET_Z + 0.02 * w     # breathing
    shoot("sleep_futon", i)

# B. pet bed: sitting curled up in a round cat bed, head drooping
for i in range(8):
    reset()
    show("petbed")
    w = wave(i, 8)
    set_eyes("sleepy")
    ROOT.location = (0, 0.02, -0.44 + 0.008 * w)
    for s in (-1, 1):
        LEG[s].rotation_euler = (math.radians(-80), math.radians(-s * 10), 0)
    arm_raise(-1, -8)
    arm_raise(1, -8)
    tilt(HEAD, 14 + 2 * w)
    tails(6, 6)
    shoot("sleep_petbed", i)

# C. charging dock: standing on the glowing pad, powered down
glow_node = [n for n in dock_glow.node_tree.nodes if n.type == "EMISSION"][0]
for i in range(8):
    reset()
    show("dock")
    w = wave(i, 8)
    set_eyes("line")
    ROOT.location = (0, 0, 0.12 + 0.006 * w)
    arm_raise(-1, -4)
    arm_raise(1, -4)
    tilt(HEAD, 6)
    glow_node.inputs["Strength"].default_value = 3.5 + 2.5 * (0.5 + 0.5 * w)
    shoot("sleep_dock", i)

cam.location.z, cam.data.ortho_scale = old_cam

# ------------------------------------------------------------- outfit passes
if OUTFITS_MODE:
    PASS_CAM = "tall"
    set_cam("tall")
    pick = [a for a in ARGS if a in OUTFITS]
    # the bigger hair styles get the Santa and witch hats a little lower and a bit bigger
    # (their own copy of those outfit frames, in outfit_santa-big / outfit_witch-big)
    BIG_HATS = {"santa": SANTA, "witch": WITCH, "sunhat": SUNHAT, "beret": BERET}
    BIG_FIT = {"santa": (-0.08, 1.12), "witch": (-0.08, 1.12), "sunhat": (0.02, 1.04), "beret": (-0.03, 1.08)}
    BIG_STYLES = ("shaggy", "swept")
    for name, objs in OUTFITS.items():
        if pick and name not in pick:
            continue
        for o in objs:
            o.hide_render = False
        all_styles = STYLE_PICK
        tuck = name in HAIR_TUCK
        if name in BIG_HATS:
            STYLE_PICK = [x for x in all_styles if x not in BIG_STYLES]
            if STYLE_PICK:
                CURRENT_OUTFIT = name
                saved = tuck_hair(objs) if tuck else []
                render_states()
                untuck_hair(saved)
            STYLE_PICK = [x for x in all_styles if x in BIG_STYLES]
            if STYLE_PICK:
                fr = BIG_HATS[name]
                loc0, sc0 = fr.location.copy(), fr.scale.copy()
                dz, sc = BIG_FIT[name]
                fr.location.z += dz
                fr.scale = (sc, sc, sc)
                tufts = [o for o in HAIRSTYLES["swept"] if o.name.startswith("SweptTuft")]
                HAIRSTYLES["swept"] = [o for o in HAIRSTYLES["swept"] if o not in tufts]   # under the hat
                CURRENT_OUTFIT = name + "-big"
                saved = tuck_hair(objs) if tuck else []
                render_states()
                untuck_hair(saved)
                HAIRSTYLES["swept"] += tufts
                fr.location, fr.scale = loc0, sc0
            STYLE_PICK = all_styles
        else:
            CURRENT_OUTFIT = name
            render_states()
        for o in objs:
            o.hide_render = True
    CURRENT_OUTFIT = None
    PASS_CAM = "normal"
    set_cam("normal")

print("ALL FRAMES DONE ->", OUT_DIR)
