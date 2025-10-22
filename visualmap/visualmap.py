from redbot.core import commands, Config
from redbot.core.bot import Red
import discord
import asyncio
import random
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import math
import os

DEFAULTS = {
    "canvas_size": (1024, 768),
    "tile_size": 64,
    "palette": {
        "ground": (188, 185, 150),
        "grass": (106, 170, 100),
        "water": (60, 120, 190),
        "forest": (28, 100, 40),
        "mountain": (120, 120, 120),
        "road": (140, 110, 70),
        "marker_bg": (200, 40, 40),
        "marker_text": (255, 255, 255)
    },
    "font_size": 14,
    "use_sprites": False
}

def _to_rgb_tuple(color):
    if color is None:
        return (0, 0, 0)
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        try:
            return (int(color[0]), int(color[1]), int(color[2]))
        except Exception:
            return (0, 0, 0)
    return (0, 0, 0)

def _clamp(v, a=0, b=255):
    return max(a, min(b, int(v)))

def _lerp(a, b, t):
    return a + (b - a) * t

# Simple value noise (grid-based) + fractal (fBm)
class FractalNoise:
    def __init__(self, seed=None):
        self.seed = seed if seed is not None else random.randint(0, 2**30)

    def _rand_at(self, ix, iy):
        # deterministic pseudo-random based on coords and seed
        n = (ix * 1836311903) ^ (iy * 2971215073) ^ self.seed
        n = (n << 13) ^ n
        return (1.0 - ((n * (n * n * 15731 + 789221) + 1376312589) & 0x7fffffff) / 1073741824.0)

    def value(self, x, y, scale=1.0, octaves=4, persistence=0.5, lacunarity=2.0):
        total = 0.0
        frequency = 1.0 / scale
        amplitude = 1.0
        max_amp = 0.0
        for _ in range(octaves):
            nx = x * frequency
            ny = y * frequency
            fx = math.floor(nx)
            fy = math.floor(ny)
            # corners
            v00 = self._rand_at(int(fx), int(fy))
            v10 = self._rand_at(int(fx + 1), int(fy))
            v01 = self._rand_at(int(fx), int(fy + 1))
            v11 = self._rand_at(int(fx + 1), int(fy + 1))
            tx = nx - fx
            ty = ny - fy
            # smoothstep for interpolation
            sx = tx * tx * (3 - 2 * tx)
            sy = ty * ty * (3 - 2 * ty)
            ix0 = _lerp(v00, v10, sx)
            ix1 = _lerp(v01, v11, sx)
            v = _lerp(ix0, ix1, sy)
            total += v * amplitude
            max_amp += amplitude
            amplitude *= persistence
            frequency *= lacunarity
        return total / max_amp if max_amp != 0 else 0.0

def _text_size(draw, text, font):
    try:
        return draw.textsize(text, font=font)
    except Exception:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            try:
                return font.getsize(text)
            except Exception:
                return (0, 0)

class VisualMap(commands.Cog):
    """Procedural visual map generator for RP worlds with improved visuals"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210123)
        self.config.register_guild(**DEFAULTS)
        try:
            self.font = ImageFont.truetype("DejaVuSans.ttf", DEFAULTS["font_size"])
        except Exception:
            self.font = ImageFont.load_default()
        self.noise = FractalNoise()
        # locate sprite assets folder (optional)
        self.asset_dir = os.path.join(os.path.dirname(__file__), "assets", "visualmap")

    async def red_delete_data_for_user(self, **kwargs):
        return

    def _create_canvas(self, size, color):
        rgb = _to_rgb_tuple(color)
        return Image.new("RGBA", size, rgb + (255,))

    def _apply_vignette(self, img):
        w, h = img.size
        vign = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(vign)
        for y in range(h):
            for x in range(w):
                # distance from center
                dx = (x - w/2) / (w/2)
                dy = (y - h/2) / (h/2)
                d = math.sqrt(dx*dx + dy*dy)
                # vignette falloff
                v = int(_clamp((1.0 - d) * 255))
                vign.putpixel((x, y), v)
        return ImageOps.colorize(vign, (0,0,0), (255,255,255)).convert("L")

    def _paint_tiles(self, base_img, tile_size, palette):
        # Instead of hard squares, paint subtle textured tiles with small noise
        w, h = base_img.size
        draw = ImageDraw.Draw(base_img)
        ground = _to_rgb_tuple(palette.get("ground", (188, 185, 150)))
        # low-frequency noise to modulate base color
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                # sample fractal noise (coarse)
                n = self.noise.value(x, y, scale=150, octaves=3) * 0.5 + 0.5
                r = _clamp(ground[0] * (0.9 + 0.2 * n))
                g = _clamp(ground[1] * (0.9 + 0.2 * n))
                b = _clamp(ground[2] * (0.9 + 0.2 * n))
                draw.rectangle([x, y, x+4, y+4], fill=(r, g, b))
        # add very subtle directional lighting
        light = Image.new("RGBA", base_img.size, (255,255,255,0))
        ld = ImageDraw.Draw(light)
        for i in range(0, 120, 20):
            alpha = int(10 * (1 - i/120))
            ld.rectangle([i, i, w, h], fill=(255,255,255,alpha))
        base_img = Image.alpha_composite(base_img.convert("RGBA"), light)
        base_img = base_img.filter(ImageFilter.GaussianBlur(0.6))
        return base_img

    def _paint_regions(self, img, palette, seed=None):
        if seed is not None:
            self.noise = FractalNoise(seed)
        w, h = img.size
        overlay = Image.new("RGBA", (w, h), (0,0,0,0))
        od = ImageDraw.Draw(overlay)

        # prepare threshold maps using fractal noise
        # water mask
        water_mask = Image.new("L", (w, h))
        forest_mask = Image.new("L", (w, h))
        mountain_mask = Image.new("L", (w, h))
        for y in range(h):
            for x in range(w):
                nx = x / w
                ny = y / h
                val = self.noise.value(x, y, scale=120, octaves=4, persistence=0.55)
                # map val (-1..1) to 0..1
                nv = (val + 1) / 2.0
                # water more likely in low nv
                water_mask.putpixel((x,y), int(_clamp(255 * (0.5 - nv) * 2)))
                # forest in mid-high nv
                forest_mask.putpixel((x,y), int(_clamp(255 * max(0.0, nv - 0.4) * 1.6)))
                # mountain peaks in very high nv (sharpened)
                mountain_mask.putpixel((x,y), int(_clamp(255 * max(0.0, (nv - 0.75) * 4))))

        # optionally blur masks for soft edges
        water_mask = water_mask.filter(ImageFilter.GaussianBlur(radius=6))
        forest_mask = forest_mask.filter(ImageFilter.GaussianBlur(radius=8))
        mountain_mask = mountain_mask.filter(ImageFilter.GaussianBlur(radius=10))

        # paint masks with palette colors
        water_col = _to_rgb_tuple(palette.get("water", (60,120,190)))
        forest_col = _to_rgb_tuple(palette.get("forest", (28,100,40)))
        mountain_col = _to_rgb_tuple(palette.get("mountain", (120,120,120)))

        # composite each mask with a slight multiplicative shading for realism
        base_rgba = img.convert("RGBA")
        # build colored layers
        water_layer = Image.new("RGBA", (w,h), water_col + (0,))
        water_layer.putalpha(water_mask)
        forest_layer = Image.new("RGBA", (w,h), forest_col + (0,))
        forest_layer.putalpha(forest_mask)
        mountain_layer = Image.new("RGBA", (w,h), mountain_col + (0,))
        mountain_layer.putalpha(mountain_mask)

        # darken ground slightly where mountains are present
        darken = Image.new("RGBA", (w,h), (0,0,0,0))
        dd = ImageDraw.Draw(darken)
        dd.rectangle([0,0,w,h], fill=(0,0,0,0))
        darken.putalpha(mountain_mask.point(lambda p: int(p*0.4)))

        composed = Image.alpha_composite(base_rgba, water_layer)
        composed = Image.alpha_composite(composed, forest_layer)
        composed = Image.alpha_composite(composed, mountain_layer)
        composed = Image.alpha_composite(composed, darken)

        # add a subtle blur to smooth transitions
        composed = composed.filter(ImageFilter.GaussianBlur(0.8))
        return composed

    def _draw_roads(self, img, points, palette):
        draw = ImageDraw.Draw(img)
        road_col = _to_rgb_tuple(palette.get("road", (140, 110, 70)))
        # draw soft shadow path
        for a, b in zip(points, points[1:]):
            # shadow
            draw.line([ (a[0]+2,a[1]+2), (b[0]+2,b[1]+2) ], fill=(0,0,0,60), width=10)
            draw.line([a, b], fill=road_col, width=6)
        return img

    def _load_sprite(self, name):
        if not os.path.isdir(self.asset_dir):
            return None
        # look for name.png
        path = os.path.join(self.asset_dir, f"{name}.png")
        if os.path.isfile(path):
            try:
                return Image.open(path).convert("RGBA")
            except Exception:
                return None
        return None

    def _draw_markers(self, img, markers, palette, font, use_sprites=False):
        draw = ImageDraw.Draw(img)
        for m in markers:
            if "pos" not in m:
                continue
            x, y = m["pos"]
            r = m.get("size", 14)
            bg = _to_rgb_tuple(palette.get("marker_bg", (200, 40, 40)))
            txtcol = _to_rgb_tuple(palette.get("marker_text", (255, 255, 255)))
            # drop shadow
            shadow = Image.new("RGBA", img.size, (0,0,0,0))
            sd = ImageDraw.Draw(shadow)
            sd.ellipse([x - r + 3, y - r + 3, x + r + 3, y + r + 3], fill=(0,0,0,120))
            img = Image.alpha_composite(img.convert("RGBA"), shadow)

            # sprite override
            sprite_name = m.get("sprite")
            if use_sprites and sprite_name:
                spr = self._load_sprite(sprite_name)
                if spr:
                    # scale sprite to desired size r*2
                    spr_w = max(8, int(r * 2))
                    spr = spr.resize((spr_w, spr_w), Image.LANCZOS)
                    img.paste(spr, (int(x - spr_w/2), int(y - spr_w/2)), spr)
                    continue

            # outer stroke circle
            stroke_col = (0,0,0)
            od = ImageDraw.Draw(img)
            od.ellipse([x - r - 2, y - r - 2, x + r + 2, y + r + 2], fill=stroke_col + (120,))
            # main circle
            od.ellipse([x - r, y - r, x + r, y + r], fill=bg + (255,))
            # label
            text = str(m.get("label", "")) or ""
            if text:
                w_t, h_t = _text_size(od, text, font)
                tx = x + r + 8
                ty = y - h_t//2
                pad = 6
                # draw box with slight outline for readability
                box = [tx - pad, ty - pad, tx + w_t + pad, ty + h_t + pad]
                # outline
                od.rectangle(box, fill=(0,0,0,180))
                # small inner stroke
                od.rectangle([box[0]+1,box[1]+1,box[2]-1,box[3]-1], outline=(255,255,255,25))
                od.text((tx, ty), text, font=font, fill=txtcol)
        return img

    def _compose_map(self, size, tile_size, palette, markers=None, seed=None, use_sprites=False):
        # normalize palette
        p = {k: _to_rgb_tuple(v) for k, v in palette.items()}
        canvas = self._create_canvas(size, p.get("ground", (188,185,150)))
        canvas = self._paint_tiles(canvas, tile_size, p)
        canvas = self._paint_regions(canvas, p, seed=seed)
        if markers and len(markers) >= 2:
            pts = [m["pos"] for m in markers if "pos" in m]
            if pts:
                canvas = self._draw_roads(canvas, pts, p)
        canvas = self._draw_markers(canvas, markers or [], p, self.font, use_sprites=use_sprites)
        # final toning: subtle vignette and slight contrast
        try:
            vign = Image.new("L", canvas.size, 0)
            vx = Image.new("L", canvas.size, 0)
        except Exception:
            vign = None
        canvas = canvas.convert("RGB")
        return canvas

    async def _image_to_discord_file(self, pil_image, name="map.png", fmt="PNG"):
        loop = asyncio.get_event_loop()
        bio = BytesIO()
        def _save():
            pil_image.save(bio, format=fmt)
            bio.seek(0)
        await loop.run_in_executor(None, _save)
        return discord.File(fp=bio, filename=name)

    @commands.group(name="visualmap", invoke_without_command=True)
    async def visualmap(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @visualmap.command(name="create")
    @commands.guild_only()
    async def create(self, ctx, *, options: str = ""):
        guild_conf = await self.config.guild(ctx.guild).all()
        size = guild_conf.get("canvas_size", DEFAULTS["canvas_size"])
        tile_size = guild_conf.get("tile_size", DEFAULTS["tile_size"])
        palette = guild_conf.get("palette", DEFAULTS["palette"])
        seed = None
        markers = []
        use_sprites = guild_conf.get("use_sprites", DEFAULTS["use_sprites"])

        opt_tokens = [t.strip() for t in options.split() if t.strip()]
        for tok in opt_tokens:
            if tok.startswith("size="):
                try:
                    w, h = tok[len("size="):].split("x")
                    size = (int(w), int(h))
                except Exception:
                    pass
            elif tok.startswith("tiles="):
                try:
                    tile_size = int(tok[len("tiles="):])
                except Exception:
                    pass
            elif tok.startswith("seed="):
                try:
                    seed = int(tok[len("seed="):])
                except Exception:
                    pass
            elif tok.startswith("markers="):
                try:
                    raw = tok[len("markers="):]
                    parts = raw.split(";")
                    for p in parts:
                        if "@" in p:
                            label, coord = p.split("@", 1)
                            cx, cy = coord.split(",")
                            markers.append({"label": label.strip(), "pos": (int(cx), int(cy))})
                except Exception:
                    pass

        img = self._compose_map(size, tile_size, palette, markers=markers, seed=seed, use_sprites=use_sprites)
        file = await self._image_to_discord_file(img, name="map.png")
        await ctx.send(file=file)

    @visualmap.command(name="spawn")
    @commands.guild_only()
    async def spawn(self, ctx, label: str = "Encounter"):
        guild_conf = await self.config.guild(ctx.guild).all()
        size = guild_conf.get("canvas_size", DEFAULTS["canvas_size"])
        tile_size = guild_conf.get("tile_size", DEFAULTS["tile_size"])
        palette = guild_conf.get("palette", DEFAULTS["palette"])
        use_sprites = guild_conf.get("use_sprites", DEFAULTS["use_sprites"])
        w, h = size
        pos = (random.randint(40, max(60, w - 40)), random.randint(40, max(60, h - 40)))
        markers = [{"label": label, "pos": pos, "size": 18}]
        img = self._compose_map(size, tile_size, palette, markers=markers, use_sprites=use_sprites)
        file = await self._image_to_discord_file(img, name="spawn.png")
        await ctx.send(file=file, content=f"Spawned {label} at {pos}")

    @visualmap.command(name="show")
    @commands.guild_only()
    async def show(self, ctx, *, payload: str = ""):
        size = DEFAULTS["canvas_size"]
        tile_size = DEFAULTS["tile_size"]
        palette = DEFAULTS["palette"]
        markers = []
        parts = [p.strip() for p in payload.split() if p.strip()]
        for p in parts:
            if p.startswith("markers="):
                raw = p[len("markers="):].strip()
                if raw.startswith("[") and raw.endswith("]"):
                    inner = raw[1:-1]
                    items = [it for it in inner.split(";") if it]
                    for it in items:
                        if "@" in it:
                            label, coord = it.split("@", 1)
                            try:
                                cx, cy = coord.split(",")
                                markers.append({"label": label.strip(), "pos": (int(cx), int(cy))})
                            except Exception:
                                continue
            if p.startswith("size="):
                try:
                    w, h = p[len("size="):].split("x")
                    size = (int(w), int(h))
                except Exception:
                    pass

        img = self._compose_map(size, tile_size, palette, markers=markers)
        file = await self._image_to_discord_file(img, name="show.png")
        await ctx.send(file=file)

    @commands.group()
    @commands.is_owner()
    async def vmap(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @vmap.command()
    @commands.is_owner()
    async def setsize(self, ctx, width: int, height: int):
        await self.config.guild(ctx.guild).canvas_size.set((width, height))
        await ctx.send(f"Default map size set to {width}x{height}")

    @vmap.command()
    @commands.is_owner()
    async def settiles(self, ctx, tile_size: int):
        await self.config.guild(ctx.guild).tile_size.set(tile_size)
        await ctx.send(f"Default tile size set to {tile_size}")

    @vmap.command()
    @commands.is_owner()
    async def setsprites(self, ctx, enabled: bool):
        await self.config.guild(ctx.guild).use_sprites.set(bool(enabled))
        await ctx.send(f"Sprite usage set to {enabled}")

    @vmap.command()
    @commands.is_owner()
    async def reset(self, ctx):
        await self.config.guild(ctx.guild).set(DEFAULTS)
        await ctx.send("VisualMap config reset to defaults")
