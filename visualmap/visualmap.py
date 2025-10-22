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

    def _create_canvas(self, size, color):
        img = Image.new("RGBA", size, color + (255,))
        return img

    def _paint_tiles(self, base_img, tile_size, palette):
        w, h = base_img.size
        draw = ImageDraw.Draw(base_img)
        tiles_x = w // tile_size + 1
        tiles_y = h // tile_size + 1
        for tx in range(tiles_x):
            for ty in range(tiles_y):
                jitter = lambda c: max(0, min(255, c + random.randint(-8, 8)))
                color = tuple(jitter(c) for c in palette["ground"])
                x0 = tx * tile_size
                y0 = ty * tile_size
                x1 = x0 + tile_size
                y1 = y0 + tile_size
                draw.rectangle([x0, y0, x1, y1], fill=color)
        base_img = base_img.filter(ImageFilter.GaussianBlur(0.3))
        return base_img

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
            cx = random.randint(0, w)
            cy = random.randint(0, h)
            rx = random.randint(w // 10, w // 4)
            ry = random.randint(h // 12, h // 5)
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
                color = palette.get(rtype, (100, 100, 100))
                draw.ellipse(ellipse_bbox, fill=color + (220,))
        img = Image.alpha_composite(img.convert("RGBA"), overlay)
        return img

    def _draw_roads(self, img, points, palette):
        draw = ImageDraw.Draw(img)
        for a, b in zip(points, points[1:]):
            draw.line([a, b], fill=palette["road"], width=6)
        return img

    def _draw_markers(self, img, markers, palette, font):
        draw = ImageDraw.Draw(img)
        for m in markers:
            x, y = m["pos"]
            r = m.get("size", 14)
            bg = palette.get("marker_bg", (200, 40, 40))
            txtcol = palette.get("marker_text", (255, 255, 255))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=bg + (255,))
            text = m.get("label", "")
            if text:
                w, h = draw.textsize(text, font=font)
                tx = x + r + 6
                ty = y - h // 2
                pad = 4
                draw.rectangle([tx - pad, ty - pad, tx + w + pad, ty + h + pad], fill=(0, 0, 0, 180))
                draw.text((tx, ty), text, font=font, fill=txtcol)
        return img

    def _compose_map(self, size, tile_size, palette, markers=None, seed=None):
        canvas = self._create_canvas(size, palette["ground"])
        canvas = self._paint_tiles(canvas, tile_size, palette)
        canvas = self._paint_regions(canvas, palette, seed=seed)
        if markers and len(markers) >= 2:
            pts = [m["pos"] for m in markers if "pos" in m]
            canvas = self._draw_roads(canvas, pts, palette)
        canvas = self._draw_markers(canvas, markers or [], palette, self.font)
        canvas = canvas.convert("RGB")
        return canvas

    async def _image_to_discord_file(self, pil_image, name="map.png", fmt="PNG"):
        loop = asyncio.get_event_loop()
        bio = BytesIO()
        def _save():
            pil_image.save(bio, format=fmt)
            bio.seek(0)
        await loop.run_in_executor(None, _save)
        discord_file = discord.File(fp=bio, filename=name)
        return discord_file

    @commands.group(name="visualmap", invoke_without_command=True)
    async def visualmap(self, ctx):
        """Visual map generation commands group"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

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
        pos = (random.randint(40, w - 40), random.randint(40, h - 40))
        markers = [{"label": label, "pos": pos, "size": 16}]
        img = self._compose_map(size, tile_size, palette, markers=markers)
        file = await self._image_to_discord_file(img, name="spawn.png")
        await ctx.send(file=file, content=f"Spawned {label} at {pos}")

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
