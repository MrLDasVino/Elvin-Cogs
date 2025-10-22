from redbot.core import commands, Config
from redbot.core.bot import Red
import discord
import asyncio
import random
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter

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
    "font_size": 14
}

def _rand_choice_weighted(items):
    total = sum(w for _, w in items)
    r = random.uniform(0, total)
    upto = 0
    for item, weight in items:
        if upto + weight >= r:
            return item
        upto += weight
    return items[-1][0]

def _to_rgb_tuple(color):
    """Accept list or tuple like [r,g,b] or (r,g,b) and return (r,g,b)."""
    if color is None:
        return (0, 0, 0)
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        try:
            return (int(color[0]), int(color[1]), int(color[2]))
        except Exception:
            return (0, 0, 0)
    return (0, 0, 0)

def _text_size(draw, text, font):
    """
    Cross-version helper to get text size.
    Returns (width, height).
    """
    try:
        # Pillow older versions
        return draw.textsize(text, font=font)
    except Exception:
        try:
            # Pillow newer versions: textbbox
            bbox = draw.textbbox((0, 0), text, font=font)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            try:
                return font.getsize(text)
            except Exception:
                return (0, 0)

class VisualMap(commands.Cog):
    """Procedural visual map generator for RP worlds"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123)
        self.config.register_guild(**DEFAULTS)
        try:
            self.font = ImageFont.truetype("arial.ttf", DEFAULTS["font_size"])
        except Exception:
            self.font = ImageFont.load_default()

    async def red_delete_data_for_user(self, **kwargs):
        return

    # Helper to create an empty canvas
    def _create_canvas(self, size, color):
        rgb = _to_rgb_tuple(color)
        img = Image.new("RGBA", size, rgb + (255,))
        return img

    # Tile pattern generator
    def _paint_tiles(self, base_img, tile_size, palette):
        w, h = base_img.size
        draw = ImageDraw.Draw(base_img)
        tiles_x = max(1, w // tile_size + 1)
        tiles_y = max(1, h // tile_size + 1)
        base_ground = _to_rgb_tuple(palette.get("ground", (188, 185, 150)))
        for tx in range(tiles_x):
            for ty in range(tiles_y):
                jitter = lambda c: max(0, min(255, int(c) + random.randint(-8, 8)))
                color = tuple(jitter(c) for c in base_ground)
                x0 = tx * tile_size
                y0 = ty * tile_size
                x1 = x0 + tile_size
                y1 = y0 + tile_size
                draw.rectangle([x0, y0, x1, y1], fill=color)
        base_img = base_img.filter(ImageFilter.GaussianBlur(0.3))
        return base_img

    # Add regions using masks
    def _paint_regions(self, img, palette, seed=None):
        if seed is not None:
            random.seed(seed)
        w, h = img.size
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        region_types = [
            ("forest", 0.5),
            ("water", 0.3),
            ("mountain", 0.2)
        ]
        count = random.randint(3, 7)
        for _ in range(count):
            rtype = _rand_choice_weighted(region_types)
            cx = random.randint(0, max(1, w))
            cy = random.randint(0, max(1, h))
            rx = random.randint(max(10, w // 10), max(20, w // 4))
            ry = random.randint(max(10, h // 12), max(20, h // 5))
            n = random.randint(3, 8)
            for i in range(n):
                jitterx = random.randint(-rx // 3, rx // 3)
                jittery = random.randint(-ry // 3, ry // 3)
                rrx = max(10, int(rx * random.uniform(0.6, 1.0)))
                rry = max(10, int(ry * random.uniform(0.6, 1.0)))
                ellipse_bbox = [
                    cx + jitterx - rrx,
                    cy + jittery - rry,
                    cx + jitterx + rrx,
                    cy + jittery + rry
                ]
                color_rgb = _to_rgb_tuple(palette.get(rtype, (100, 100, 100)))
                draw.ellipse(ellipse_bbox, fill=color_rgb + (220,))
        img = Image.alpha_composite(img.convert("RGBA"), overlay)
        return img

    # Draw simple roads between markers
    def _draw_roads(self, img, points, palette):
        draw = ImageDraw.Draw(img)
        road_col = _to_rgb_tuple(palette.get("road", (140, 110, 70)))
        for a, b in zip(points, points[1:]):
            draw.line([a, b], fill=road_col, width=6)
        return img

    # Markers: labeled circles
    def _draw_markers(self, img, markers, palette, font):
        draw = ImageDraw.Draw(img)
        for m in markers:
            if "pos" not in m:
                continue
            x, y = m["pos"]
            r = m.get("size", 14)
            bg = _to_rgb_tuple(palette.get("marker_bg", (200, 40, 40)))
            txtcol = _to_rgb_tuple(palette.get("marker_text", (255, 255, 255)))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=bg + (255,))
            text = str(m.get("label", "")) or ""
            if text:
                w, h = _text_size(draw, text, font)
                tx = x + r + 6
                ty = y - h // 2
                pad = 4
                draw.rectangle([tx - pad, ty - pad, tx + w + pad, ty + h + pad], fill=(0, 0, 0, 180))
                draw.text((tx, ty), text, font=font, fill=txtcol)
        return img

    # Compose full map
    def _compose_map(self, size, tile_size, palette, markers=None, seed=None):
        canvas = self._create_canvas(size, palette.get("ground", (188, 185, 150)))
        canvas = self._paint_tiles(canvas, tile_size, palette)
        canvas = self._paint_regions(canvas, palette, seed=seed)
        if markers and len(markers) >= 2:
            pts = [m["pos"] for m in markers if "pos" in m]
            if pts:
                canvas = self._draw_roads(canvas, pts, palette)
        canvas = self._draw_markers(canvas, markers or [], palette, self.font)
        canvas = canvas.convert("RGB")
        return canvas

    # Utility to save to BytesIO asynchronously
    async def _image_to_discord_file(self, pil_image, name="map.png", fmt="PNG"):
        loop = asyncio.get_event_loop()
        bio = BytesIO()
        def _save():
            pil_image.save(bio, format=fmt)
            bio.seek(0)
        await loop.run_in_executor(None, _save)
        discord_file = discord.File(fp=bio, filename=name)
        return discord_file

    # Command group (top-level visualmap)
    @commands.group(name="visualmap", invoke_without_command=True)
    async def visualmap(self, ctx):
        """Visual map generation commands group"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # Create a map and return image
    @visualmap.command(name="create")
    @commands.guild_only()
    async def create(self, ctx, *, options: str = ""):
        """
        Create a procedural map.
        Options format example:
        size=800x600 tiles=64 seed=42 markers=Town@200,150;Camp@400,300
        """
        guild_conf = await self.config.guild(ctx.guild).all()
        size = guild_conf.get("canvas_size", DEFAULTS["canvas_size"])
        tile_size = guild_conf.get("tile_size", DEFAULTS["tile_size"])
        palette = guild_conf.get("palette", DEFAULTS["palette"])
        seed = None
        markers = []

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

        img = self._compose_map(size, tile_size, palette, markers=markers, seed=seed)
        file = await self._image_to_discord_file(img, name="map.png")
        await ctx.send(file=file)

    # Spawn a random encounter marker and return updated map
    @visualmap.command(name="spawn")
    @commands.guild_only()
    async def spawn(self, ctx, label: str = "Encounter"):
        """
        Spawn a random marker on a small map and send image.
        """
        guild_conf = await self.config.guild(ctx.guild).all()
        size = guild_conf.get("canvas_size", DEFAULTS["canvas_size"])
        tile_size = guild_conf.get("tile_size", DEFAULTS["tile_size"])
        palette = guild_conf.get("palette", DEFAULTS["palette"])
        w, h = size
        pos = (random.randint(40, max(60, w - 40)), random.randint(40, max(60, h - 40)))
        markers = [{"label": label, "pos": pos, "size": 16}]
        img = self._compose_map(size, tile_size, palette, markers=markers)
        file = await self._image_to_discord_file(img, name="spawn.png")
        await ctx.send(file=file, content=f"Spawned {label} at {pos}")

    # Show map with specified markers inline JSON-like arg for devs
    @visualmap.command(name="show")
    @commands.guild_only()
    async def show(self, ctx, *, payload: str = ""):
        """
        Show a map with inline payload describing markers.
        Example payload:
        markers=[Town@100,200;Gate@300,400] size=640x480
        """
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

    # Admin config command for adjusting defaults
    @commands.group()
    @commands.is_owner()
    async def vmap(self, ctx):
        """Visual map admin commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @vmap.command()
    @commands.is_owner()
    async def setsize(self, ctx, width: int, height: int):
        """Set default canvas size"""
        await self.config.guild(ctx.guild).canvas_size.set((width, height))
        await ctx.send(f"Default map size set to {width}x{height}")

    @vmap.command()
    @commands.is_owner()
    async def settiles(self, ctx, tile_size: int):
        """Set default tile size"""
        await self.config.guild(ctx.guild).tile_size.set(tile_size)
        await ctx.send(f"Default tile size set to {tile_size}")

    @vmap.command()
    @commands.is_owner()
    async def reset(self, ctx):
        """Reset guild config to defaults"""
        await self.config.guild(ctx.guild).set(DEFAULTS)
        await ctx.send("VisualMap config reset to defaults")
