# ============================================================================
#  PARALLAX MAKER - Easy Create Parallax With One Click
#  Addon Blender 3.6.x | Rebuild UI & Fitur Setara Versi Superhive
#  (c) Parallax Maker Team
# ============================================================================
#
#  Buat efek parallax (gambar 2D menjadi terlihat 3D / bergerak kedalaman)
#  hanya dengan SATU KLIK, langsung dari Image Editor.
#
#  CARA PAKAI:
#    1. Install addon ini (Edit > Preferences > Add-ons > Install...)
#       lalu aktifkan "Parallax Maker".
#    2. Buka IMAGE EDITOR, pilih gambar / sequence video Anda.
#    3. Klik tombol [ PARALLAX ] pada header Image Editor -> muncul panel.
#    4. Atur Depth Map, Zoom, Motion, Blur, Vignette, dll.
#    5. Tekan RENDER untuk menghasilkan video parallax (FFmpeg),
#       atau PREVIEW di viewport untuk melihat hasilnya secara realtime.
#
# ============================================================================

bl_info = {
    "name": "Parallax Maker",
    "description": "Easy create parallax with one click - ubah gambar 2D "
                   "menjadi animasi parallax 3D dengan depth map, zoom, "
                   "motion, blur, vignette dan color grading.",
    "author": "Parallax Maker Team",
    "version": (3, 6, 0),
    "blender": (3, 6, 0),
    "location": "Image Editor > Header (tombol PARALLAX)",
    "warning": "",
    "doc_url": "",
    "category": "Animation",
}

import bpy
import os
import re
from math import radians, sqrt
from bpy.props import (
    StringProperty, BoolProperty, FloatProperty, IntProperty, EnumProperty,
    FloatVectorProperty, PointerProperty,
)

SEQ_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.tga')


# ============================================================================
#  UTILITAS
# ============================================================================

def get_addon_pref():
    """Ambil addon preferences (folder preset)."""
    return getattr(bpy.context.preferences.addons, __name__, None)


def get_preset_folder():
    pref = get_addon_pref()
    if pref is not None:
        return bpy.path.abspath(pref.preset_folder)
    return ""


def natural_key(string_):
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]


def get_sequence_path(path):
    """Kembalikan (files_list, ext, folder, base_name, start_index)
    dari path file / sequence."""
    files = []
    ext = ''
    folder = ''
    name = ''
    start = 1
    if not path:
        return files, ext, folder, name, start
    path = bpy.path.abspath(path)
    folder = os.path.dirname(path)
    filename = os.path.basename(path)
    if os.path.isfile(path):
        try:
            with open(path, 'rb') as f:
                head = f.read(12)
            # File image tunggal? cek magic number umum image
            if (head[:3] == b'\xff\xd8\xff' or head[:8] == b'\x89PNG\r\n\x1a\n'
                    or head[:2] == b'BM' or head[:4] in (b'II*\x00', b'MM\x00*'
                    ) or head[:3] == b'GIF' or b'truevision' in head[8:12]):
                files.append(filename)
                ext = os.path.splitext(filename)[1].lower()
                name = os.path.splitext(filename)[0]
                return files, ext, folder, name, start
        except OSError:
            pass
    # Perlakukan sebagai sequence: cari frame lain di folder yang sama
    base, e = os.path.splitext(filename)
    digits = ''.join(ch for ch in base if ch.isdigit())
    wildcard = base.replace(digits, '*' + ('?' * len(digits))) + e
    wildcard_re = re.compile(
        '^' + re.escape(wildcard).replace('\\*', '.').replace('\\?', '.') + '$')
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder), key=natural_key):
            if fn.lower().endswith(SEQ_EXT) and wildcard_re.match(fn):
                files.append(fn)
        if files:
            ext = e.lower()
            name = base.replace(digits, '')
            first = os.path.splitext(files[0])[0]
            d = ''.join(ch for ch in first if ch.isdigit())
            start = int(d) if d else 1
    return files, ext, folder, name, start


def pm_source_enum(self, context):
    """Enum daftar image untuk properti Source Image."""
    items = [("", "Not Set", "")]
    for i in bpy.data.images:
        if not i.name.startswith("PM_"):
            items.append((i.name, i.name, ""))
    return items


def get_image_from_area(area):
    """Ambil image aktif dari sebuah Image Editor area (dengan fallback
    ke image pertama di blend)."""
    img = None
    try:
        space = area.spaces.active
        if space.image:
            img = space.image
        elif space.source == 'SEQUENCE':
            scene_seq = space.sequence_clip
            if scene_seq and scene_seq.image:
                img = scene_seq.image
    except Exception:
        img = None
    if img is None:
        for i in bpy.data.images:
            if (not i.name.startswith("PM_")) and (i.has_data or i.filepath):
                img = i
                break
    return img


def set_view2d_zoom(region, view2d, center_x, center_y, zoom):
    """Zoom region 2D pada titik tertentu (dipakai scroll wheel preview)."""
    rdx = region.width / 2.0
    rdy = region.height / 2.0
    minx = rdx + (center_x - rdx) * zoom
    maxx = rdx + (center_x + rdx) * zoom
    miny = rdy + (center_y - rdy) * zoom
    maxy = rdy + (center_y + rdy) * zoom
    view2d.cur_rotation = 0.0
    view2d.zoom_to_region(region, (minx, miny, maxx, maxy))


# ============================================================================
#  PROPERTI SCENE (seluruh parameter Parallax Maker)
# ============================================================================

class PMSceneProps(bpy.types.PropertyGroup):
    pm_version: StringProperty(name="Version", default="3.6.0")
    pm_export: BoolProperty(name="Export", default=False)
    pm_source_image: EnumProperty(name="Source Image",
                                  description="Image sumber parallax",
                                  items=pm_source_enum)
    pm_depth_map: StringProperty(name="Depth Map", subtype='FILE_PATH')
    pm_depth_channel: EnumProperty(
        name="Channel",
        items=[('R', "R", ""), ('G', "G", ""), ('B', "B", ""),
               ('RGB', "RGB", "")],
        default='R')
    pm_invert_depth: BoolProperty(name="Invert", default=False)
    pm_auto_depth: BoolProperty(name="Auto Depth", default=False)
    pm_preview_quality: EnumProperty(
        name="Preview Quality",
        items=[('LOW', "Low", ""), ('MEDIUM', "Medium", ""),
               ('HIGH', "High", "")],
        default='MEDIUM')
    pm_frames: IntProperty(name="Frames", default=60, min=1, max=10000)
    pm_fps: IntProperty(name="FPS", default=24, min=1, max=240)
    pm_res: FloatProperty(name="Res %", default=100.0, min=1.0, max=1000.0)
    pm_format: EnumProperty(
        name="Format",
        items=[('MP4', "MP4", ""), ('WEBM', "WEBM", ""),
               ('PNG', "PNG Sequence", ""), ('AVI', "AVI", "")],
        default='MP4')
    pm_output: StringProperty(name="Output", subtype='DIR_PATH')
    pm_offset: FloatProperty(name="Offset", default=0.0, min=-1000.0,
                             max=1000.0)
    pm_motion_type: EnumProperty(
        name="Motion",
        items=[('LINEAR', "Linear", ""), ('CIRCLE', "Circle", ""),
               ('HORIZONTAL', "Horizontal", ""), ('VERTICAL', "Vertical", ""),
               ('RANDOM', "Random", "")],
        default='LINEAR')
    pm_motion_speed: FloatProperty(name="Speed", default=1.0, min=0.0,
                                   max=100.0)
    pm_intensity: FloatProperty(name="Intensity", default=100.0, min=0.0,
                                max=1000.0)
    pm_zoom: FloatProperty(name="Zoom", default=100.0, min=0.0, max=1000.0)
    pm_blur: FloatProperty(name="Blur", default=0.0, min=0.0, max=100.0)
    pm_lens_enabled: BoolProperty(name="Camera Lens", default=True)
    pm_lens_shape: EnumProperty(
        name="Lens Shape",
        items=[('BOX', "Box", ""), ('SPHERE', "Sphere", ""),
               ('CYLINDER_X', "Cylinder X", ""),
               ('CYLINDER_Y', "Cylinder Y", "")],
        default='BOX')
    pm_lens_size: FloatProperty(name="Lens Size", default=100.0, min=1.0,
                                max=1000.0)
    pm_lens_position: FloatProperty(name="Position", default=0.0,
                                    min=-1000.0, max=1000.0)
    pm_lens_focus: FloatProperty(name="Focus", default=0.0, min=-1000.0,
                                 max=1000.0)
    pm_vignette: FloatProperty(name="Vignette", default=0.0, min=0.0,
                               max=100.0)
    pm_saturation: FloatProperty(name="Saturation", default=100.0, min=0.0,
                                 max=300.0)
    pm_contrast: FloatProperty(name="Contrast", default=100.0, min=0.0,
                               max=300.0)
    pm_gamma: FloatProperty(name="Gamma", default=100.0, min=1.0, max=300.0)
    pm_exposure: FloatProperty(name="Exposure", default=0.0, min=-5.0,
                               max=5.0)
    pm_grain: FloatProperty(name="Grain", default=0.0, min=0.0, max=100.0)
    pm_color_enabled: BoolProperty(name="Color Grading", default=False)
    pm_shadows_color: FloatVectorProperty(name="Shadows", size=3,
                                          default=(0.0, 0.0, 0.1),
                                          subtype='COLOR')
    pm_highlights_color: FloatVectorProperty(name="Highlights", size=3,
                                             default=(0.1, 0.05, 0.0),
                                             subtype='COLOR')
    pm_blend_mode: EnumProperty(
        name="Blend",
        items=[('MIX', "Mix", ""), ('ADD', "Add", ""),
               ('MULTIPLY', "Multiply", ""), ('SCREEN', "Screen", "")],
        default='MIX')
    pm_overlay_enabled: BoolProperty(name="Overlay", default=False)
    pm_overlay_image: StringProperty(name="Overlay Image",
                                     subtype='FILE_PATH')
    pm_overlay_opacity: FloatProperty(name="Opacity", default=50.0, min=0.0,
                                      max=100.0)
    pm_preset: StringProperty(name="Preset")


# ============================================================================
#  OPERATOR: BUKA / TUTUP PANEL PARALLAX (TOMBOL HEADER)
# ============================================================================

class PM_OT_open_panel(bpy.types.Operator):
    """Buka / tutup panel Parallax Maker pada Image Editor"""
    bl_idname = "pm.open_panel"
    bl_label = "Open Panel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None

    def execute(self, context):
        if context.area is None:
            return {'CANCELLED'}
        props = context.area.spaces.active
        show = props.get("pm_panel", False)
        props["pm_panel"] = not show
        context.area.tag_redraw()
        return {'FINISHED'}


# ============================================================================
#  OPERATOR: PREVIEW DI VIEWPORT (Realtime OpenGL Preview)
# ============================================================================

class PM_OT_preview(bpy.types.Operator):
    """Nyalakan / matikan preview parallax realtime di Image Editor.
    Gunakan scroll mouse untuk zoom, ESC untuk keluar."""
    bl_idname = "pm.preview"
    bl_label = "Preview"
    bl_description = "Toggle realtime parallax preview on the image"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None

    @classmethod
    def poll(cls, context):
        return (context.area is not None
                and context.area.type == 'IMAGE_EDITOR')

    def execute(self, context):
        space = context.area.spaces.active
        if space.get("pm_preview_on", False):
            # matikan preview
            space["pm_preview_on"] = False
            img = get_image_from_area(context.area)
            if img:
                space.image = img
            if PM_OT_preview._timer:
                context.window_manager.timers.remove(PM_OT_preview._timer)
                PM_OT_preview._timer = None
            context.area.tag_redraw()
            self.report({'INFO'}, "Parallax preview dimatikan")
            return {'FINISHED'}

        img = get_image_from_area(context.area)
        if img is None:
            self.report({'WARNING'}, "Tidak ada image di Image Editor!")
            return {'CANCELLED'}

        w, h = img.size
        if w == 0 or h == 0:
            self.report({'WARNING'}, "Image tidak memiliki ukuran!")
            return {'CANCELLED'}

        context.scene.pm_props.pm_source_image = img.name

        # buat / ambil datablock preview
        pm_img = bpy.data.images.get("PM_PREVIEW")
        if pm_img is None:
            pm_img = bpy.data.images.new("PM_PREVIEW", w, h, alpha=False,
                                         float_buffer=False)
        elif (pm_img.size[0], pm_img.size[1]) != (w, h):
            pm_img.scale(w, h)

        # simpan state awal
        space["pm_preview_on"] = True
        space["pm_orig_w"] = float(img.size[0])
        space["pm_orig_h"] = float(img.size[1])
        space["pm_center_x"] = float(img.size[0]) / 2.0
        space["pm_center_y"] = float(img.size[1]) / 2.0
        space["pm_zoomf"] = 1.0
        space["pm_frame"] = 0
        space.image = pm_img

        if PM_OT_preview._timer is None:
            PM_OT_preview._timer = context.window_manager.timers.new(
                1.0 / max(1, context.scene.pm_props.pm_fps), None)
        context.area.tag_redraw()
        self.report({'INFO'}, "Parallax preview aktif (scroll=zoom)")
        return {'FINISHED'}

    # ------------------ inti perhitungan preview per frame ------------------
    @staticmethod
    def update_preview(context):
        space = context.area.spaces.active
        scene = context.scene
        p = scene.pm_props
        orig = bpy.data.images.get(p.pm_source_image or "")
        pm_img = bpy.data.images.get("PM_PREVIEW")
        if orig is None or pm_img is None:
            return
        # pastikan yang tampil adalah preview
        if space.image != pm_img:
            space.image = pm_img

        ow = int(space.get("pm_orig_w", orig.size[0]))
        oh = int(space.get("pm_orig_h", orig.size[1]))
        if ow == 0 or oh == 0:
            return

        frame = int(space.get("pm_frame", 0))
        total = max(1, p.pm_frames)
        t = frame / float(total)

        # ---- kualitas preview (render internal lebih besar lalu downscale)
        qmul = {'LOW': 1.0, 'MEDIUM': 1.5, 'HIGH': 2.5}.get(
            p.pm_preview_quality, 1.5)
        rw = max(2, int(ow * qmul))
        rh = max(2, int(oh * qmul))

        # ---- sumber pixel (image asli)
        src = list(orig.pixels[:])
        if len(src) != ow * oh * 4:
            return

        # ---- depth map (dimuat via datablock image, cache per filepath)
        depth = None
        if p.pm_depth_map:
            dpath = bpy.path.abspath(p.pm_depth_map)
            if os.path.isfile(dpath):
                cache = bpy.data.images.get("PM_DEPTH_CACHE")
                if cache is None or cache.get("pm_src", "") != dpath:
                    if cache is not None:
                        bpy.data.images.remove(cache)
                    try:
                        cache = bpy.data.images.load(dpath)
                        cache["pm_src"] = dpath
                    except Exception:
                        cache = None
                if cache is not None and cache.size[0] and cache.size[1]:
                    dw, dh = cache.size
                    raw = list(cache.pixels[:])
                    # nearest resize ke resolusi render
                    depth = [0.0] * (rw * rh)
                    ch = p.pm_depth_channel
                    inv = p.pm_invert_depth
                    for y in range(rh):
                        sy = min(dh - 1, int(y * dh / rh))
                        rowbase = sy * dw
                        outbase = y * rw
                        for x in range(rw):
                            sx = min(dw - 1, int(x * dw / rw))
                            i = (rowbase + sx) * 4
                            if ch == 'R':
                                v = raw[i]
                            elif ch == 'G':
                                v = raw[i + 1]
                            elif ch == 'B':
                                v = raw[i + 2]
                            else:
                                v = (raw[i] + raw[i + 1] + raw[i + 2]) / 3.0
                            if inv:
                                v = 1.0 - v
                            depth[outbase + x] = v

        # ---- auto depth (grayscale luminance dipakai sebagai depth)
        if depth is None and p.pm_auto_depth:
            depth = [0.0] * (rw * rh)
            for y in range(rh):
                sy = min(oh - 1, int(y * oh / rh))
                rowbase = sy * ow
                outbase = y * rw
                for x in range(rw):
                    sx = min(ow - 1, int(x * ow / rw))
                    i = (rowbase + sx) * 4
                    depth[outbase + x] = (src[i] * 0.299 + src[i + 1] * 0.587
                                          + src[i + 2] * 0.114)

        # ---- motion offset per frame
        inten = p.pm_intensity * 0.01
        speed = p.pm_motion_speed
        ox = oy = 0.0
        mt = p.pm_motion_type
        if mt == 'LINEAR':
            ox = (t * 2.0 - 1.0) * speed * 0.15 * inten
        elif mt == 'CIRCLE':
            ox = sqrt(max(0.0, 1.0 - (t * 2.0 - 1.0) ** 2)) * \
                (1 if t < 0.5 else -1) * speed * 0.15 * inten
            oy = ((t * 2.0 - 1.0) * 0.5) * speed * 0.15 * inten
        elif mt == 'HORIZONTAL':
            ox = ((t * 2.0 - 1.0)) * speed * 0.2 * inten
        elif mt == 'VERTICAL':
            oy = ((t * 2.0 - 1.0)) * speed * 0.2 * inten
        elif mt == 'RANDOM':
            import random
            rnd = random.Random(frame)
            ox = (rnd.random() - 0.5) * speed * 0.1 * inten
            oy = (rnd.random() - 0.5) * speed * 0.1 * inten

        ox += p.pm_offset * 0.01

        zoom_f = max(0.01, p.pm_zoom * 0.01)
        blur_r = p.pm_blur * 0.01
        vig = p.pm_vignette * 0.01
        sat = p.pm_saturation * 0.01
        con = p.pm_contrast * 0.01
        gam = max(0.01, p.pm_gamma * 0.01)
        expo = p.pm_exposure
        grain = p.pm_grain * 0.01
        lens_on = p.pm_lens_enabled
        lens_size = max(1.0, p.pm_lens_size) * 0.01
        focus = p.pm_lens_focus * 0.01
        col_on = p.pm_color_enabled
        sh_c = p.pm_shadows_color
        hi_c = p.pm_highlights_color
        ov_on = p.pm_overlay_enabled

        out = [0.0] * (rw * rh * 4)

        # overlay image (cache sederhana per filepath)
        ov_raw = None
        if ov_on and p.pm_overlay_image:
            opath = bpy.path.abspath(p.pm_overlay_image)
            if os.path.isfile(opath):
                cache = bpy.data.images.get("PM_OVERLAY_CACHE")
                if cache is None or cache.get("pm_src", "") != opath:
                    if cache is not None:
                        bpy.data.images.remove(cache)
                    try:
                        cache = bpy.data.images.load(opath)
                        cache["pm_src"] = opath
                    except Exception:
                        cache = None
                if cache is not None and cache.size[0] and cache.size[1]:
                    ov_raw = (list(cache.pixels[:]), cache.size[0],
                              cache.size[1])

        cx = rw / 2.0
        cy = rh / 2.0

        for y in range(rh):
            fy = (y + 0.5) / rh          # 0..1
            ny = fy * 2.0 - 1.0          # -1..1
            for x in range(rw):
                fx = (x + 0.5) / rw
                nx = fx * 2.0 - 1.0

                d = depth[y * rw + x] if depth is not None else 0.5

                # posisi source (normalized) dengan zoom, shift, parallax
                sxn = 0.5 + (fx - 0.5) / zoom_f
                syn = 0.5 + (fy - 0.5) / zoom_f
                sxn += ox * d
                syn += oy * d

                # camera lens distortion
                if lens_on:
                    lx = nx / (lens_size * 1.2)
                    ly = ny / (lens_size * 1.2)
                    shape = p.pm_lens_shape
                    r2 = lx * lx + ly * ly
                    if shape == 'BOX':
                        k = 1.0 + focus * (abs(lx) ** 2 + abs(ly) ** 2) * 0.5
                    elif shape == 'SPHERE':
                        k = 1.0 + focus * (sqrt(max(0.0, 1.0 - r2)) - 1.0) \
                            * 0.5
                    elif shape == 'CYLINDER_X':
                        k = 1.0 + focus * (abs(lx) - 1.0) * 0.5
                    else:  # CYLINDER_Y
                        k = 1.0 + focus * (abs(ly) - 1.0) * 0.5
                    sxn = 0.5 + (sxn - 0.5) * k
                    syn = 0.5 + (syn - 0.5) * k

                # sample bilinear dari source
                u = sxn * ow - 0.5
                v = syn * oh - 0.5
                u = max(0.0, min(ow - 1.001, u))
                v = max(0.0, min(oh - 1.001, v))
                ix, iy = int(u), int(v)
                tx, ty = u - ix, v - iy
                i00 = (iy * ow + ix) * 4
                i10 = i00 + 4
                i01 = i00 + ow * 4
                i11 = i01 + 4
                r = (src[i00] * (1 - tx) + src[i10] * tx) * (1 - ty) + \
                    (src[i01] * (1 - tx) + src[i11] * tx) * ty
                g = (src[i00 + 1] * (1 - tx) + src[i10 + 1] * tx) * (1 - ty) \
                    + (src[i01 + 1] * (1 - tx) + src[i11 + 1] * tx) * ty
                b = (src[i00 + 2] * (1 - tx) + src[i10 + 2] * tx) * (1 - ty) \
                    + (src[i01 + 2] * (1 - tx) + src[i11 + 2] * tx) * ty

                # simple depth-of-field / defocus blur approximation
                if blur_r > 0.0:
                    radius = int(blur_r * rw * 0.05 * (0.35 + abs(d - 0.5)))
                    if radius > 0:
                        rr = gg = bb = cnt = 0.0
                        step = max(1, radius)
                        for dy2 in range(-radius, radius + 1, step):
                            uy = max(0, min(oh - 1, iy + dy2))
                            for dx2 in range(-radius, radius + 1, step):
                                ux = max(0, min(ow - 1, ix + dx2))
                                j = (uy * ow + ux) * 4
                                rr += src[j]
                                gg += src[j + 1]
                                bb += src[j + 2]
                                cnt += 1
                        if cnt:
                            r = (r + rr / cnt) * 0.5
                            g = (g + gg / cnt) * 0.5
                            b = (b + bb / cnt) * 0.5

                # color grading dasar
                r *= pow(2.0, expo)
                g *= pow(2.0, expo)
                b *= pow(2.0, expo)
                lum = r * 0.299 + g * 0.587 + b * 0.114
                r = lum + (r - lum) * sat
                g = lum + (g - lum) * sat
                b = lum + (b - lum) * sat
                r = (r - 0.5) * con + 0.5
                g = (g - 0.5) * con + 0.5
                b = (b - 0.5) * con + 0.5
                if gam != 1.0:
                    r = max(0.0, r) ** (1.0 / gam)
                    g = max(0.0, g) ** (1.0 / gam)
                    b = max(0.0, b) ** (1.0 / gam)

                # split tone shadows / highlights
                if col_on:
                    tl = max(0.0, min(1.0, lum))
                    sw = (1.0 - tl) ** 2
                    hw = tl ** 2
                    r = r * (1 - sw * 0.5) + sh_c[0] * sw * 0.5 \
                        + hi_c[0] * hw * 0.3
                    g = g * (1 - sw * 0.5) + sh_c[1] * sw * 0.5 \
                        + hi_c[1] * hw * 0.3
                    b = b * (1 - sw * 0.5) + sh_c[2] * sw * 0.5 \
                        + hi_c[2] * hw * 0.3

                # vignette
                if vig > 0.0:
                    vd = sqrt(nx * nx * 0.55 + ny * ny * 0.55)
                    vf = 1.0 - vig * max(0.0, vd - 0.35) * 2.0
                    r *= vf
                    g *= vf
                    b *= vf

                # film grain
                if grain > 0.0:
                    import random as _rd
                    gn = (_rd.Random(x * 7919 + y * 104729 + frame * 31)
                          .random() - 0.5) * grain * 0.5
                    r += gn
                    g += gn
                    b += gn

                # overlay
                if ov_raw is not None:
                    oraw, odw, odh = ov_raw
                    ou = int(fx * (odw - 1))
                    ov2 = int(fy * (odh - 1))
                    j = (ov2 * odw + ou) * 4
                    a = oraw[j + 3] * (p.pm_overlay_opacity * 0.01)
                    r = r * (1 - a) + oraw[j] * a
                    g = g * (1 - a) + oraw[j + 1] * a
                    b = b * (1 - a) + oraw[j + 2] * a

                o = (y * rw + x) * 4
                out[o] = min(1.0, max(0.0, r))
                out[o + 1] = min(1.0, max(0.0, g))
                out[o + 2] = min(1.0, max(0.0, b))
                out[o + 3] = 1.0

        pm_img.scale(rw, rh)
        pm_img.pixels = out
        pm_img.update()

        # fit view agar hasil selalu terlihat penuh
        for region in context.area.regions:
            if region.type == 'WINDOW':
                v2d = space.view2d
                v2d.region_2d_bind_to(region)
                z = space.get("pm_zoomf", 1.0)
                set_view2d_zoom(region, v2d, rw / 2.0, rh / 2.0, z)
        context.area.tag_redraw()

    def modal(self, context, event):
        if context.area is None or context.area.type != 'IMAGE_EDITOR':
            return self.cancel(context)
        space = context.area.spaces.active
        if not space.get("pm_preview_on", False):
            return self.cancel(context)

        p = context.scene.pm_props
        if event.type == 'TIMER':
            frame = int(space.get("pm_frame", 0)) + 1
            if frame >= p.pm_frames:
                frame = 0
            space["pm_frame"] = frame
            try:
                self.update_preview(context)
            except Exception as err:
                print("[ParallaxMaker] preview error:", err)
                return self.cancel(context)
            return {'PASS_THROUGH'}

        if event.type == 'ESC':
            return self.execute(context)

        # scroll = zoom preview
        if event.type in {'MOUSEWHEELUP', 'MOUSEWHEELDOWN'} \
                and event.value == 'PRESS':
            z = space.get("pm_zoomf", 1.0)
            z *= 1.1 if event.type == 'MOUSEWHEELUP' else 1 / 1.1
            z = max(0.05, min(50.0, z))
            space["pm_zoomf"] = z
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'}

    def cancel(self, context):
        if PM_OT_preview._timer:
            context.window_manager.timers.remove(PM_OT_preview._timer)
            PM_OT_preview._timer = None
        return {'FINISHED'}

    def invoke(self, context, event):
        res = self.execute(context)
        if res == {'FINISHED'} and context.area.spaces.active.get(
                "pm_preview_on", False):
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return res


# ============================================================================
#  OPERATOR: RENDER PARALLAX (Compositor -> Video/Image Sequence)
# ============================================================================

class PM_OT_render(bpy.types.Operator):
    """Render animasi parallax sesuai semua parameter"""
    bl_idname = "pm.render"
    bl_label = "Render"
    bl_description = "Render parallax ke video / image sequence"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        p = context.scene.pm_props
        img = bpy.data.images.get(p.pm_source_image or "")
        if (img is None or img.name.startswith("PM_")) \
                and context.area and context.area.type == 'IMAGE_EDITOR':
            img = get_image_from_area(context.area)
        if img is None:
            self.report({'ERROR'}, "Tidak ada image! Buka image di "
                                   "Image Editor dulu.")
            return {'CANCELLED'}

        p.pm_source_image = img.name

        # --- siapkan scene render
        scene = context.scene
        scene.frame_start = 1
        scene.frame_end = p.pm_frames
        scene.render.fps = p.pm_fps

        ow, oh = img.size
        res_mul = p.pm_res / 100.0
        rw = max(2, int(ow * res_mul))
        rh = max(2, int(oh * res_mul))
        scene.render.resolution_x = rw
        scene.render.resolution_y = rh
        scene.render.resolution_percentage = 100

        fmt = p.pm_format
        if fmt == 'MP4':
            scene.render.image_settings.file_format = 'FFMPEG'
            scene.render.ffmpeg.format = 'MPEG4'
            scene.render.ffmpeg.codec = 'H264'
            scene.render.ffmpeg.constant_rate_factor = 'HIGH'
        elif fmt == 'WEBM':
            scene.render.image_settings.file_format = 'FFMPEG'
            scene.render.ffmpeg.format = 'WEBM'
            scene.render.ffmpeg.codec = 'VP9'
        elif fmt == 'AVI':
            scene.render.image_settings.file_format = 'FFMPEG'
            scene.render.ffmpeg.format = 'AVI'
            scene.render.ffmpeg.codec = 'FFV1'
        else:  # PNG sequence
            scene.render.image_settings.file_format = 'PNG'

        out = bpy.path.abspath(p.pm_output) if p.pm_output else \
            os.path.join(os.path.dirname(bpy.data.filepath) or
                         os.path.expanduser("~"), "parallax_output")
        os.makedirs(out, exist_ok=True)
        base = "parallax_" + (img.name.replace('.', '_') or "render")
        if fmt == 'PNG':
            scene.render.filepath = os.path.join(out, base + "_####")
        else:
            scene.render.filepath = os.path.join(out, base)

        # --- bangun node compositor
        self.build_nodes(scene, img, p, rw, rh)

        scene.render.use_compositing = True
        scene.render.use_sequencer = False

        # --- render animation (non-blocking via INVOKE_DEFAULT bila bisa)
        try:
            bpy.ops.render.render('INVOKE_DEFAULT', animation=True,
                                  use_compositing=True)
        except Exception:
            bpy.ops.render.render(animation=True, use_compositing=True)
        self.report({'INFO'}, "Render parallax dimulai... output: " + out)
        return {'FINISHED'}

    # ------------------------------------------------------------------
    def build_nodes(self, scene, img, p, rw, rh):
        scene.use_nodes = True
        nt = scene.node_tree
        nt.nodes.clear()
        links = nt.links

        def N(t, x, y, **kw):
            n = nt.nodes.new(t)
            n.location = (x, y)
            for k, v in kw.items():
                setattr(n, k, v)
            return n

        R = p.pm_intensity * 0.01
        motion_x = max(0.05, abs(p.pm_offset) * 0.01 +
                       p.pm_motion_speed * 0.1) * R
        motion_y = max(0.05, abs(p.pm_offset) * 0.01 +
                       p.pm_motion_speed * 0.1) * R

        texorig = N('CompositorNodeImage', -1400, 400, image=img)
        texorig.label = "Source Image"

        # --- depth map
        has_depth = bool(p.pm_depth_map) and os.path.isfile(
            bpy.path.abspath(p.pm_depth_map))
        if has_depth:
            dimg = N('CompositorNodeImage', -1400, 100)
            try:
                dib = bpy.data.images.load(bpy.path.abspath(p.pm_depth_map))
                dimg.image = dib
            except Exception:
                pass
            dsep = N('CompositorNodeSepRGBA', -1150, 100)
            links.new(dimg.outputs['Image'], dsep.inputs['Image'])
            if p.pm_depth_channel == 'RGB':
                drgb = N('CompositorNodeRGBToBW', -980, 100)
                links.new(dimg.outputs['Image'], drgb.inputs['Image'])
                depth_out = drgb.outputs['Val']
            else:
                depth_out = dsep.outputs[p.pm_depth_channel]
            if p.pm_invert_depth:
                dinv = N('CompositorNodeInvert', -800, 100)
                links.new(depth_out, dinv.inputs['Color'])
                depth_out = dinv.outputs['Color']
        else:
            dbw = N('CompositorNodeRGBToBW', -1150, 100)
            links.new(texorig.outputs['Image'], dbw.inputs['Image'])
            depth_out = dbw.outputs['Val']

        # --- displacement (parallax warp berbasis depth)
        # Catatan: node Displace Blender 3.6 memakai input terpisah
        # 'X Scale' dan 'Y Scale' (bukan vektor 'Scale').
        disp = N('CompositorNodeDisplace', -700, 300)
        links.new(texorig.outputs['Image'], disp.inputs['Image'])
        # vector driver dari depth (statis), gerakan lewat keyframe X/Y Scale
        vec = N('CompositorNodeCombineXYZ', -900, -100)
        links.new(depth_out, vec.inputs['X'])
        links.new(depth_out, vec.inputs['Y'])
        vec.inputs['Z'].default_value = 0.5
        links.new(vec.outputs['Vector'], disp.inputs['Vector'])
        # keyframe skala displacement sepanjang waktu (sesuai motion type)
        total = p.pm_frames
        step = max(1, total // 12)
        for fr in range(1, total + 1, step):
            t = (fr - 1) / float(max(1, total - 1))
            if p.pm_motion_type == 'LINEAR':
                vx = (t * 2 - 1) * motion_x
                vy = 0.0
            elif p.pm_motion_type == 'CIRCLE':
                vx = -((t * 2 - 1)) * motion_x
                vy = sqrt(max(0.0, 1 - (t * 2 - 1) ** 2)) * \
                    (1 if t < .5 else -1) * motion_y
            elif p.pm_motion_type == 'HORIZONTAL':
                vx = (t * 2 - 1) * motion_x
                vy = 0.0
            elif p.pm_motion_type == 'VERTICAL':
                vx = 0.0
                vy = (t * 2 - 1) * motion_x
            else:
                import random
                rd = random.Random(fr)
                vx = (rd.random() - .5) * motion_x
                vy = (rd.random() - .5) * motion_y
            disp.inputs['X Scale'].default_value = vx
            disp.inputs['Y Scale'].default_value = vy
            disp.inputs['X Scale'].keyframe_insert('default_value', frame=fr)
            disp.inputs['Y Scale'].keyframe_insert('default_value', frame=fr)

        # --- zoom (Transform node; input 'Scale' adalah VALUE tunggal)
        scale_n = N('CompositorNodeTransform', -450, 300)
        scale_n.inputs['Scale'].default_value = p.pm_zoom * 0.01
        links.new(disp.outputs['Image'], scale_n.inputs['Image'])

        cur = scale_n.outputs['Image']

        # --- camera lens (Lens Distortion node: input 'Distort')
        if p.pm_lens_enabled:
            lens = N('CompositorNodeLensdist', -250, 300)
            ls = p.pm_lens_size * 0.01
            lens.inputs['Distort'].default_value = \
                max(-1.0, min(1.0, p.pm_lens_focus * 0.01 * ls))
            try:
                lens.use_fit = True
                lens.use_jitter = (p.pm_lens_shape == 'SPHERE')
                lens.use_projector = (p.pm_lens_shape != 'BOX')
            except Exception:
                pass
            links.new(cur, lens.inputs['Image'])
            cur = lens.outputs['Image']

        # --- blur / depth of field (Blur node: input 'Size')
        if p.pm_blur > 0.0:
            blur = N('CompositorNodeBlur', -50, 300)
            blur.filter_type = 'FAST_GAUSS'
            blur.inputs['Size'].default_value = max(
                1.0, p.pm_blur * 0.5)
            links.new(cur, blur.inputs['Image'])
            cur = blur.outputs['Image']

        # --- vignette (Ellipse Mask -> Color Ramp -> Multiply)
        if p.pm_vignette > 0.0:
            ellipse = N('CompositorNodeEllipseMask', -250, -200)
            ellipse.width = 1.0
            ellipse.height = 1.0
            ramp = N('CompositorNodeValToRGB', -50, -200)
            ramp.color_ramp.elements[0].position = 0.0
            ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
            ramp.color_ramp.elements[1].position = max(
                0.05, 1.0 - p.pm_vignette * 0.01)
            ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
            try:
                ramp.interpolation = 'B_SPLINE'
            except Exception:
                pass
            links.new(ellipse.outputs['Mask'], ramp.inputs['Fac'])
            mixv = N('CompositorNodeMixRGB', 150, 300, blend_type='MULTIPLY')
            mixv.inputs['Fac'].default_value = 1.0
            links.new(cur, mixv.inputs[1])
            links.new(ramp.outputs['Color'], mixv.inputs[2])
            cur = mixv.outputs['Image']

        # --- color grading
        if abs(p.pm_saturation - 100) > 0.01 or \
                abs(p.pm_contrast - 100) > 0.01 or \
                abs(p.pm_gamma - 100) > 0.01 or abs(p.pm_exposure) > 0.001:
            hsv = N('CompositorNodeHueSat', 350, 300)
            hsv.inputs['Saturation'].default_value = p.pm_saturation * 0.01
            hsv.inputs['Value'].default_value = max(
                0.0, 1.0 + p.pm_exposure * 0.3)
            hsv.inputs['Color Value'].default_value = max(
                0.01, p.pm_gamma * 0.01)
            links.new(cur, hsv.inputs['Image'])
            cur = hsv.outputs['Image']
            mr = N('CompositorNodeMapRange', 500, 300)
            cval = max(0.01, p.pm_contrast * 0.01)
            mr.inputs['From Min'].default_value = 0.5 - 0.5 / cval
            mr.inputs['From Max'].default_value = 0.5 + 0.5 / cval
            links.new(cur, mr.inputs['Value'])
            cur = mr.outputs['Result']

        # --- split toning
        if p.pm_color_enabled:
            blend_map = {'MIX': 'MIX', 'ADD': 'ADD',
                         'MULTIPLY': 'MULTIPLY', 'SCREEN': 'SCREEN'}
            mixs = N('CompositorNodeMixRGB', 850, 300,
                     blend_type=blend_map.get(p.pm_blend_mode, 'MIX'))
            mixs.inputs['Fac'].default_value = 0.25
            rgbsh = N('CompositorNodeRGB', 650, -150)
            rgbsh.outputs[0].default_value = (*p.pm_shadows_color, 1.0)
            links.new(cur, mixs.inputs[1])
            links.new(rgbsh.outputs[0], mixs.inputs[2])
            cur = mixs.outputs['Image']

        # --- film grain
        if p.pm_grain > 0.0:
            noise = N('CompositorNodeTexNoise', 650, 550)
            noise.noise_scale = 0.01
            noise.inputs['Detail'].default_value = 2.0
            nramp = N('CompositorNodeValToRGB', 850, 550)
            nramp.color_ramp.elements[0].position = 0.4
            nramp.color_ramp.elements[1].position = 0.6
            links.new(noise.outputs['Fac'], nramp.inputs['Fac'])
            mixg = N('CompositorNodeMixRGB', 1050, 300,
                     blend_type='OVERLAY')
            mixg.inputs['Fac'].default_value = p.pm_grain * 0.01 * 0.5
            links.new(cur, mixg.inputs[1])
            links.new(nramp.outputs['Color'], mixg.inputs[2])
            cur = mixg.outputs['Image']

        # --- overlay
        if p.pm_overlay_enabled and p.pm_overlay_image and os.path.isfile(
                bpy.path.abspath(p.pm_overlay_image)):
            ovimg = N('CompositorNodeImage', 1050, 550)
            try:
                ovimg.image = bpy.data.images.load(
                    bpy.path.abspath(p.pm_overlay_image))
            except Exception:
                pass
            blend_map = {'MIX': 'MIX', 'ADD': 'ADD',
                         'MULTIPLY': 'MULTIPLY', 'SCREEN': 'SCREEN'}
            mixo = N('CompositorNodeMixRGB', 1250, 300,
                     blend_type=blend_map.get(p.pm_blend_mode, 'MIX'))
            mixo.inputs['Fac'].default_value = p.pm_overlay_opacity * 0.01
            links.new(cur, mixo.inputs[1])
            links.new(ovimg.outputs['Image'], mixo.inputs[2])
            cur = mixo.outputs['Image']

        composite = N('CompositorNodeComposite', 1450, 300)
        links.new(cur, composite.inputs['Image'])


# ============================================================================
#  OPERATOR: EXPORT SEQUENCE FRAMES
# ============================================================================

class PM_OT_export(bpy.types.Operator):
    """Export hasil parallax menjadi image sequence (PNG frames)"""
    bl_idname = "pm.export"
    bl_label = "Export"
    bl_description = "Export frames sebagai image sequence"
    bl_options = {'REGISTER'}

    def execute(self, context):
        p = context.scene.pm_props
        old_fmt = p.pm_format
        p.pm_format = 'PNG'
        bpy.ops.pm.render()
        p.pm_format = old_fmt
        self.report({'INFO'}, "Export sequence dijalankan via render.")
        return {'FINISHED'}


# ============================================================================
#  OPERATOR: LOAD DEPTH MAP (file browser)
# ============================================================================

class PM_OT_load_depth(bpy.types.Operator):
    """Muat Depth Map dari file browser"""
    bl_idname = "pm.load_depth"
    bl_label = "Load Depth Map"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_ext: BoolProperty(default=True)

    def execute(self, context):
        if self.filepath:
            context.scene.pm_props.pm_depth_map = self.filepath
            self.report({'INFO'}, "Depth map dimuat: "
                                + os.path.basename(self.filepath))
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ============================================================================
#  OPERATOR: LOAD OVERLAY IMAGE (file browser)
# ============================================================================

class PM_OT_load_overlay(bpy.types.Operator):
    """Muat Overlay Image dari file browser"""
    bl_idname = "pm.load_overlay"
    bl_label = "Load Overlay"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        if self.filepath:
            context.scene.pm_props.pm_overlay_image = self.filepath
            self.report({'INFO'}, "Overlay dimuat.")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ============================================================================
#  OPERATOR: SAVE / LOAD PRESET (JSON)
# ============================================================================

PRESET_KEYS = ("pm_depth_map", "pm_depth_channel", "pm_invert_depth",
               "pm_auto_depth", "pm_preview_quality", "pm_frames", "pm_fps",
               "pm_res", "pm_format", "pm_output", "pm_offset",
               "pm_motion_type", "pm_motion_speed", "pm_intensity", "pm_zoom",
               "pm_blur", "pm_lens_enabled", "pm_lens_shape", "pm_lens_size",
               "pm_lens_position", "pm_lens_focus", "pm_vignette",
               "pm_saturation", "pm_contrast", "pm_gamma", "pm_exposure",
               "pm_grain", "pm_color_enabled", "pm_shadows_color",
               "pm_highlights_color", "pm_blend_mode", "pm_overlay_enabled",
               "pm_overlay_image", "pm_overlay_opacity")


def collect_preset_values(p):
    data = {}
    for k in PRESET_KEYS:
        v = getattr(p, k)
        data[k] = list(v) if isinstance(v, tuple) else v
    return data


def apply_preset_values(p, data):
    for k, v in data.items():
        if k.startswith("pm_") and hasattr(p, k):
            try:
                if isinstance(v, list):
                    setattr(p, k, tuple(v))
                else:
                    setattr(p, k, v)
            except Exception:
                pass


class PM_OT_save_preset(bpy.types.Operator):
    """Simpan pengaturan saat ini sebagai preset"""
    bl_idname = "pm.save_preset"
    bl_label = "Save Preset"
    bl_description = "Simpan preset ke folder preset"
    bl_options = {'REGISTER'}

    name: StringProperty(name="Preset Name", default="My Preset")

    def execute(self, context):
        import json
        folder = get_preset_folder()
        if not folder:
            folder = os.path.join(os.path.expanduser("~"), ".pm_presets")
        os.makedirs(folder, exist_ok=True)
        fp = os.path.join(folder, self.name.strip() + ".json")
        with open(fp, 'w') as f:
            json.dump(collect_preset_values(context.scene.pm_props), f,
                      indent=2)
        self.report({'INFO'}, "Preset disimpan: " + fp)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class PM_OT_load_preset(bpy.types.Operator):
    """Muat preset dari folder preset"""
    bl_idname = "pm.load_preset"
    bl_label = "Load Preset"
    bl_description = "Muat preset yang pernah disimpan"
    bl_options = {'REGISTER'}

    def presets_enum(self, context):
        items = []
        folder = get_preset_folder()
        if folder and os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                if fn.endswith(".json"):
                    items.append((fn[:-5], fn[:-5], ""))
        if not items:
            items = [("NONE", "No Presets Found", "")]
        return items

    preset_name: EnumProperty(name="Preset", items=presets_enum)

    def execute(self, context):
        import json
        if self.preset_name == "NONE":
            self.report({'WARNING'}, "Belum ada preset tersimpan.")
            return {'CANCELLED'}
        fp = os.path.join(get_preset_folder(), self.preset_name + ".json")
        try:
            with open(fp) as f:
                apply_preset_values(context.scene.pm_props, json.load(f))
            self.report({'INFO'}, "Preset dimuat: " + self.preset_name)
        except Exception as err:
            self.report({'ERROR'}, "Gagal memuat preset: %s" % err)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


# ============================================================================
#  OPERATOR: RESET
# ============================================================================

class PM_OT_reset(bpy.types.Operator):
    """Reset seluruh parameter ke default"""
    bl_idname = "pm.reset"
    bl_label = "Reset"
    bl_description = "Reset parameter ke nilai awal"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.pm_props
        defaults = dict(pm_depth_map="", pm_depth_channel='R',
                        pm_invert_depth=False, pm_auto_depth=False,
                        pm_preview_quality='MEDIUM', pm_frames=60, pm_fps=24,
                        pm_res=100.0, pm_format='MP4', pm_output="",
                        pm_offset=0.0, pm_motion_type='LINEAR',
                        pm_motion_speed=1.0, pm_intensity=100.0, pm_zoom=100.0,
                        pm_blur=0.0, pm_lens_enabled=True,
                        pm_lens_shape='BOX', pm_lens_size=100.0,
                        pm_lens_position=0.0, pm_lens_focus=0.0,
                        pm_vignette=0.0, pm_saturation=100.0,
                        pm_contrast=100.0, pm_gamma=100.0, pm_exposure=0.0,
                        pm_grain=0.0, pm_color_enabled=False,
                        pm_blend_mode='MIX', pm_overlay_enabled=False,
                        pm_overlay_image="", pm_overlay_opacity=50.0)
        for k, v in defaults.items():
            setattr(p, k, v)
        self.report({'INFO'}, "Parameter direset.")
        return {'FINISHED'}


# ============================================================================
#  UI: HEADER TOGGLE BUTTON
# ============================================================================

def draw_header_button(self, context):
    layout = self.layout
    show = False
    if context.area and context.area.type == 'IMAGE_EDITOR':
        show = context.area.spaces.active.get("pm_panel", False)
    icon = 'RESTRICT_VIEW_OFF' if show else 'IMAGE_ZDEPTH'
    layout.separator()
    layout.operator(PM_OT_open_panel.bl_idname, text="PARALLAX",
                    toggle=show, icon=icon)


# ============================================================================
#  UI: PANEL UTAMA (Sidebar Image Editor, tab Parallax Maker)
# ============================================================================

class PM_PT_main(bpy.types.Panel):
    bl_label = "Parallax Maker"
    bl_idname = "PM_PT_main"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Parallax Maker"

    @classmethod
    def poll(cls, context):
        if context.area is None:
            return False
        return context.area.spaces.active.get("pm_panel", False)

    def draw(self, context):
        scene = context.scene
        p = scene.pm_props
        layout = self.layout
        box = layout.box()

        # ================= SOURCE =================
        row = box.row(align=True)
        row.label(text="SOURCE", icon='IMAGE_DATA')
        row.prop(p, "pm_source_image", text="")
        r2 = box.row(align=True)
        r2.operator(PM_OT_preview.bl_idname, text="Preview",
                    icon='RESTRICT_RENDER_OFF')
        r2.operator(PM_OT_render.bl_idname, text="Render",
                    icon='RESTRICT_RENDER_ON')

        # ================= DEPTH MAP =================
        col = box.column(align=True)
        col.label(text="DEPTH MAP", icon='COLOR')
        r = col.row(align=True)
        r.prop(p, "pm_depth_map", text="")
        r.operator(PM_OT_load_depth.bl_idname, text="", icon='FILE_FOLDER')
        r = col.row(align=True)
        r.prop(p, "pm_depth_channel", text="")
        r.prop(p, "pm_invert_depth", toggle=True)
        r.prop(p, "pm_auto_depth", toggle=True, text="Auto")
        col.prop(p, "pm_preview_quality", text="Quality")

        # ================= ANIMATION =================
        col = box.column(align=True)
        col.label(text="ANIMATION", icon='ANIM')
        col.prop(p, "pm_frames")
        col.prop(p, "pm_fps")
        col.prop(p, "pm_res", text="Resolution %")
        col.prop(p, "pm_format", text="")
        r = col.row(align=True)
        r.prop(p, "pm_output", text="Output")
        r.prop(p, "pm_export", toggle=True, text="Export", icon='EXPORT')

        # ================= MOTION =================
        col = box.column(align=True)
        col.label(text="MOTION", icon='EFF')
        col.prop(p, "pm_offset")
        col.prop(p, "pm_motion_type", text="")
        col.prop(p, "pm_motion_speed")
        col.prop(p, "pm_intensity")
        col.prop(p, "pm_zoom")
        col.prop(p, "pm_blur")

        # ================= CAMERA LENS =================
        col = box.column(align=True)
        col.prop(p, "pm_lens_enabled", toggle=True, text="CAMERA LENS",
                 icon='CAMERA_DATA')
        if p.pm_lens_enabled:
            col.prop(p, "pm_lens_shape", text="")
            col.prop(p, "pm_lens_size")
            col.prop(p, "pm_lens_position")
            col.prop(p, "pm_lens_focus")

        # ================= EFFECTS =================
        col = box.column(align=True)
        col.label(text="EFFECTS", icon='LIGHT')
        col.prop(p, "pm_vignette")
        col.prop(p, "pm_saturation")
        col.prop(p, "pm_contrast")
        col.prop(p, "pm_gamma")
        col.prop(p, "pm_exposure")
        col.prop(p, "pm_grain")

        # ================= COLOR GRADING =================
        col = box.column(align=True)
        col.prop(p, "pm_color_enabled", toggle=True, text="COLOR GRADING",
                 icon='COLOR_MANAGE')
        if p.pm_color_enabled:
            col.prop(p, "pm_shadows_color")
            col.prop(p, "pm_highlights_color")
            col.prop(p, "pm_blend_mode", text="")

        # ================= OVERLAY =================
        col = box.column(align=True)
        col.prop(p, "pm_overlay_enabled", toggle=True, text="OVERLAY",
                 icon='OVERLAY')
        if p.pm_overlay_enabled:
            r = col.row(align=True)
            r.prop(p, "pm_overlay_image", text="")
            r.operator(PM_OT_load_overlay.bl_idname, text="",
                       icon='FILE_FOLDER')
            col.prop(p, "pm_overlay_opacity")

        # ================= PRESETS =================
        col = box.column(align=True)
        col.label(text="PRESETS", icon='BOOKMARKS')
        r = col.row(align=True)
        r.operator(PM_OT_save_preset.bl_idname, text="Save",
                   icon='DISK')
        r.operator(PM_OT_load_preset.bl_idname, text="Load",
                   icon='FILE_REFRESH')
        r.operator(PM_OT_reset.bl_idname, text="Reset", icon='CANCEL')

        # footer versi
        row = box.row()
        row.alignment = 'CENTER'
        row.label(text="Version: " + p.pm_version, icon='INFO')


# ============================================================================
#  ADDON PREFS
# ============================================================================

class PM_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    preset_folder: StringProperty(
        name="Preset Folder", subtype='DIR_PATH',
        description="Folder penyimpanan preset Parallax Maker",
        default=os.path.join(os.path.expanduser("~"), ".pm_presets"))

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "preset_folder")


# ============================================================================
#  REGISTER
# ============================================================================

classes = (
    PMSceneProps,
    PM_OT_open_panel,
    PM_OT_preview,
    PM_OT_render,
    PM_OT_export,
    PM_OT_load_depth,
    PM_OT_load_overlay,
    PM_OT_save_preset,
    PM_OT_load_preset,
    PM_OT_reset,
    PM_PT_main,
    PM_Preferences,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pm_props = PointerProperty(type=PMSceneProps)
    # properti status panel disimpan langsung di space (space["pm_panel"])
    # sehingga tidak perlu menambah property baru ke ImageEditorSpaceParams.
    bpy.types.IMAGE_HT_header.append(draw_header_button)


def unregister():
    bpy.types.IMAGE_HT_header.remove(draw_header_button)
    del bpy.types.Scene.pm_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
