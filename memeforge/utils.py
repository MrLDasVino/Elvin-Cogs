from urllib.parse import quote


def encode_text(text: str) -> str:
    if not text:
        return "_"
    text = text.replace("_", "__")
    text = text.replace("\n", "~n")
    text = text.replace("?", "~q")
    text = text.replace("&", "~a")
    text = text.replace("%", "~p")
    text = text.replace("#", "~h")
    text = text.replace("/", "~s")
    text = text.replace("\\", "~b")
    text = text.replace("<", "~l")
    text = text.replace(">", "~g")
    text = text.replace('"', "''")
    text = text.replace(" ", "_")
    return quote(text)


def build_image_url(base_url: str, template_id: str, lines: list) -> str:
    lines = [line for line in lines]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return f"{base_url}/images/{template_id}.png"
    encoded = [encode_text(line) for line in lines]
    path = "/".join(encoded)
    return f"{base_url}/images/{template_id}/{path}.png"
