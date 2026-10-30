"""Generate synthetic, shareable screenshots for demos and evaluation.

    python generate_samples.py

Writes samples/demo (a few images to try the app) and samples/eval (the
evaluation set plus queries.json with relevance labels). Every image is drawn
here, so nothing private ends up in the repository.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = (800, 500)
ROOT = Path(__file__).parent / "samples"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def text_screen(lines, bg="#ffffff", fg="#222222", title_color=None, bar="#e0e0e0"):
    img = Image.new("RGB", SIZE, bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, SIZE[0], 36], fill=bar)
    for i, x in enumerate((16, 40, 64)):
        d.ellipse([x, 12, x + 12, 24], fill=["#ff5f57", "#febc2e", "#28c840"][i])
    y = 70
    for i, line in enumerate(lines):
        size = 34 if i == 0 else 24
        d.text((40, y), line, font=font(size), fill=(title_color or fg) if i == 0 else fg)
        y += size + 18
    return img


def shape_screen(bg, shapes):
    img = Image.new("RGB", SIZE, bg)
    d = ImageDraw.Draw(img)
    for kind, box, color in shapes:
        if kind == "rect":
            d.rectangle(box, fill=color)
        elif kind == "round":
            d.rounded_rectangle(box, radius=24, fill=color)
        elif kind == "ellipse":
            d.ellipse(box, fill=color)
        elif kind == "poly":
            d.polygon(box, fill=color)
    return img


def gradient(top, bottom):
    img = Image.new("RGB", SIZE)
    d = ImageDraw.Draw(img)
    for y in range(SIZE[1]):
        t = y / SIZE[1]
        d.line([(0, y), (SIZE[0], y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def stripes(colors, width=60, vertical=True):
    img = Image.new("RGB", SIZE)
    d = ImageDraw.Draw(img)
    for i in range(0, SIZE[0] if vertical else SIZE[1], width):
        c = colors[(i // width) % len(colors)]
        d.rectangle([i, 0, i + width, SIZE[1]] if vertical else [0, i, SIZE[0], i + width], fill=c)
    return img


def checkerboard(a="#000000", b="#ffffff", cell=50):
    img = Image.new("RGB", SIZE, b)
    d = ImageDraw.Draw(img)
    for x in range(0, SIZE[0], cell):
        for y in range(0, SIZE[1], cell):
            if (x // cell + y // cell) % 2 == 0:
                d.rectangle([x, y, x + cell, y + cell], fill=a)
    return img


def stars(bg="#0b1026", n=120, seed=1):
    rng = random.Random(seed)
    img = Image.new("RGB", SIZE, bg)
    d = ImageDraw.Draw(img)
    for _ in range(n):
        x, y, r = rng.randrange(SIZE[0]), rng.randrange(SIZE[1]), rng.choice([1, 1, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r], fill="#ffffff")
    d.ellipse([600, 60, 700, 160], fill="#f5f3ce")
    return img


TEXT_SCREENS = {
    "pasta_recipe": dict(lines=["Spaghetti al Pomodoro", "Ingredients", "400 g spaghetti",
                                "6 ripe tomatoes, chopped", "2 cloves garlic, fresh basil",
                                "Simmer the sauce for 20 minutes"], bg="#fff8ee", fg="#4a3426"),
    "db_error": dict(lines=["psql: error", "connection to server at \"localhost\", port 5432 failed:",
                            "Connection refused", "Is the server running on that host and",
                            "accepting TCP/IP connections?"], bg="#1e1e1e", fg="#e6e6e6",
                     title_color="#ff6b6b", bar="#333333"),
    "sneaker_shop": dict(lines=["Trail Runner 2 - Ocean Blue", "$89.99", "Size: 10 US",
                                "Free shipping on orders over $50", "[ Add to cart ]"], fg="#1a237e"),
    "invoice": dict(lines=["Invoice #10423", "Billed to: Example Studio", "Design services   $1,000.00",
                           "Hosting           $250.00", "Total due: $1,250.00"]),
    "boarding_pass": dict(lines=["BOARDING PASS", "Flight SR 204  Lisbon -> Oslo", "Gate B12   Seat 14A",
                                 "Boarding 07:35"], bg="#e3f2fd", fg="#0d47a1"),
    "password_reset": dict(lines=["Reset your password", "Enter the email address linked to",
                                  "your account and we'll send a reset link.", "[ Send link ]"]),
    "team_meeting": dict(lines=["Team sync", "Thursday 3:00 PM - 3:30 PM", "Room 4B",
                                "Agenda: roadmap, hiring, launch date"]),
    "weather": dict(lines=["Weather", "Partly cloudy  18°C", "Rain expected tomorrow",
                           "Wind 12 km/h"], bg="#eef7ff"),
    "merge_conflict": dict(lines=["CONFLICT (content): Merge conflict in app.py",
                                  "Automatic merge failed; fix conflicts", "and then commit the result."],
                           bg="#0d1117", fg="#c9d1d9", title_color="#f85149", bar="#161b22"),
    "wifi_settings": dict(lines=["Wi-Fi", "Network: HomeNet", "Connected, secured",
                                 "IP address 192.168.1.24"]),
    "german_menu": dict(lines=["Speisekarte", "Käsespätzle   12,50 €", "Gulaschsuppe   8,90 €",
                               "Apfelstrudel   6,00 €"], bg="#fdf6e3"),
    "bank_transfer": dict(lines=["Transfer complete", "You sent $40.00 to Alex", "Reference: concert tickets",
                                 "Balance: $1,204.18"], fg="#1b5e20"),
    "npm_error": dict(lines=["npm ERR! code ENOENT", "npm ERR! syscall open",
                             "npm ERR! Could not read package.json"], bg="#000000", fg="#ff5555", bar="#222"),
    "python_traceback": dict(lines=["Traceback (most recent call last):", "  File \"main.py\", line 12",
                                    "    user = users[\"user_id\"]", "KeyError: 'user_id'"],
                             bg="#272822", fg="#f8f8f2", bar="#3e3d32"),
    "package_delivery": dict(lines=["Order confirmed", "Your package arrives Friday",
                                    "Tracking number 1Z999AA10123456784"]),
    "dinner_chat": dict(lines=["Sam", "Are we still on for dinner tonight?",
                               "Yes! 7pm at the Thai place", "See you there"], bg="#ece5dd"),
    "biology_notes": dict(lines=["Photosynthesis", "Light reactions occur in the thylakoid",
                                 "Calvin cycle happens in the stroma", "Produces glucose and oxygen"]),
    "battery_low": dict(lines=["Battery low", "10% remaining", "Connect your charger soon"],
                        bg="#fff3e0", title_color="#e65100"),
    "gym_schedule": dict(lines=["Weekly workout plan", "Mon: legs  Wed: back  Fri: chest",
                                "Sunday: long run 10 km"]),
    "book_list": dict(lines=["Reading list", "1. The Left Hand of Darkness", "2. Dune",
                             "3. A Wizard of Earthsea"], bg="#f3e5f5"),
}

SHAPE_SCREENS = {
    "dark_red_button": lambda: shape_screen("#121212", [("round", (300, 220, 500, 290), "#e53935")]),
    "yellow_blue_circle": lambda: shape_screen("#ffeb3b", [("ellipse", (300, 150, 500, 350), "#1e88e5")]),
    "green_stripes": lambda: stripes(["#2e7d32", "#a5d6a7"]),
    "black_square_white": lambda: shape_screen("#ffffff", [("rect", (300, 150, 500, 350), "#000000")]),
    "purple_gradient": lambda: gradient((106, 27, 154), (236, 64, 122)),
    "sunset": lambda: shape_screen("#ff7043", [("rect", (0, 330, 800, 500), "#5d4037"),
                                               ("ellipse", (330, 220, 470, 360), "#ffee58")]),
    "blue_sky_clouds": lambda: shape_screen("#81d4fa", [("ellipse", (80, 80, 300, 180), "#ffffff"),
                                                        ("ellipse", (450, 150, 700, 260), "#ffffff")]),
    "checkerboard": lambda: checkerboard(),
    "night_stars": lambda: stars(),
    "green_field": lambda: shape_screen("#64b5f6", [("rect", (0, 280, 800, 500), "#43a047")]),
    "red_stop_sign": lambda: shape_screen("#eeeeee", [("poly", [(330, 110), (470, 110), (550, 190), (550, 310),
                                                               (470, 390), (330, 390), (250, 310), (250, 190)],
                                                       "#c62828")]),
    "orange_triangle": lambda: shape_screen("#263238", [("poly", [(400, 100), (600, 400), (200, 400)], "#ff9800")]),
    "pink_background": lambda: shape_screen("#f8bbd0", []),
    "blue_buttons_row": lambda: shape_screen("#fafafa", [("round", (80 + i * 230, 220, 260 + i * 230, 280),
                                                          "#1565c0") for i in range(3)]),
    "rainbow_stripes": lambda: stripes(["#e53935", "#fb8c00", "#fdd835", "#43a047", "#1e88e5", "#8e24aa"],
                                       width=84, vertical=False),
}

QUERIES = [
    # exact text
    ("database connection refused", "exact", ["db_error"]),
    ("Invoice total due", "exact", ["invoice"]),
    ("boarding pass gate B12", "exact", ["boarding_pass"]),
    ("npm ERR could not read package.json", "exact", ["npm_error"]),
    ("KeyError user_id", "exact", ["python_traceback"]),
    ("Käsespätzle", "exact", ["german_menu"]),
    # approximate wording
    ("the pasta recipe with tomatoes", "approximate", ["pasta_recipe"]),
    ("blue sneakers I wanted to buy", "approximate", ["sneaker_shop"]),
    ("forgot my password email", "approximate", ["password_reset"]),
    ("merge conflict git", "approximate", ["merge_conflict"]),
    ("money I sent to Alex", "approximate", ["bank_transfer"]),
    ("when is my package arriving", "approximate", ["package_delivery"]),
    # visual descriptions
    ("a dark screen with a red button", "visual", ["dark_red_button"]),
    ("blue circle on a yellow background", "visual", ["yellow_blue_circle"]),
    ("night sky with stars and moon", "visual", ["night_stars"]),
    ("sunset over the ground", "visual", ["sunset"]),
    ("red stop sign", "visual", ["red_stop_sign"]),
    ("black and white checkerboard pattern", "visual", ["checkerboard"]),
    # no relevant match
    ("giraffe passport renewal", "none", []),
    ("violin concert seating chart", "none", []),
]


def build_eval(out: Path, seed: int = 7) -> None:
    """Images get neutral names (shot_NNN) so filenames don't give answers away."""
    out.mkdir(parents=True, exist_ok=True)
    images: dict[str, tuple[Image.Image, str]] = {}
    for name, spec in TEXT_SCREENS.items():
        images[name] = (text_screen(**spec), "png")
    for name, make in SHAPE_SCREENS.items():
        images[name] = (make(), "png")
    # Neutral distractors so the task isn't trivially small.
    rng = random.Random(seed)
    words = ["note", "draft", "update", "status", "list", "item", "report", "summary", "page", "view"]
    for i in range(25):
        if i % 2:
            lines = [f"{rng.choice(words).title()} {i}"] + [
                " ".join(rng.choice(words) for _ in range(6)) for _ in range(3)]
            images[f"distractor_{i}"] = (text_screen(lines), "png")
        else:
            bg = tuple(rng.randrange(60, 200) for _ in range(3))
            box = [rng.randrange(50, 350), rng.randrange(50, 200)]
            box += [box[0] + rng.randrange(100, 300), box[1] + rng.randrange(80, 200)]
            fill = tuple(rng.randrange(256) for _ in range(3))
            images[f"distractor_{i}"] = (shape_screen(bg, [("rect", box, fill)]), "jpg")

    order = list(images)
    rng.shuffle(order)
    filenames = {}
    for idx, key in enumerate(order, start=1):
        image, ext = images[key]
        filenames[key] = f"shot_{idx:03d}.{ext}"
        image.save(out / filenames[key], quality=90)  # quality only affects JPEG
    queries = [{"query": q, "kind": kind, "relevant": [filenames[r] for r in rel]}
               for q, kind, rel in QUERIES]
    (out / "queries.json").write_text(json.dumps(queries, indent=2, ensure_ascii=False), encoding="utf-8")


def build_demo(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    text_screen(["Lemon Garlic Chicken", "2 lemons, 4 cloves garlic", "Roast 40 minutes at 200°C"],
                bg="#fffde7").save(out / "recipe.png")
    text_screen(["ERROR: relation \"users\" does not exist", "LINE 1: SELECT * FROM users"],
                bg="#1e1e1e", fg="#eeeeee", title_color="#ff6b6b", bar="#333").save(out / "sql_error.png")
    text_screen(["Concert tickets", "Saturday 8:00 PM", "Row F, Seats 11-12"]).save(out / "tickets.png")
    shape_screen("#101010", [("round", (300, 220, 500, 290), "#43a047")]).save(out / "dark_green_button.png")
    shape_screen("#ffffff", [("ellipse", (250, 100, 550, 400), "#e53935")]).save(out / "red_circle.png")
    gradient((2, 136, 209), (178, 235, 242)).save(out / "blue_gradient.jpg", quality=90)


if __name__ == "__main__":
    build_eval(ROOT / "eval")
    build_demo(ROOT / "demo")
    print(f"Wrote samples to {ROOT}")
