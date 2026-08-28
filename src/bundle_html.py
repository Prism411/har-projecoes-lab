from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera o HTML único e offline.")
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def inline_script(source: str) -> str:
    return source.replace("</script", "<\\/script")


def replace_script(html: str, src: str, content: str) -> str:
    pattern = rf'<script\s+src="{re.escape(src)}"\s*></script>'
    replacement = "<script>\n" + inline_script(content) + "\n</script>"
    updated, count = re.subn(pattern, lambda _: replacement, html, count=1)
    if count != 1:
        raise ValueError(f"Referência não encontrada ou duplicada: {src}")
    return updated


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    web = root / "web"
    dist = root / "dist"
    dist.mkdir(parents=True, exist_ok=True)

    html = (web / "index.html").read_text(encoding="utf-8")
    scripts = [
        ("./vendor/react.production.min.js", web / "vendor/react.production.min.js"),
        ("./vendor/react-dom.production.min.js", web / "vendor/react-dom.production.min.js"),
        ("./support.js", web / "support.js"),
        ("./har-data.js", web / "har-data.js"),
        ("./vendor/plotly-gl3d.min.js", web / "vendor/plotly-gl3d.min.js"),
        ("./vendor/echarts.min.js", web / "vendor/echarts.min.js"),
    ]
    for src, path in scripts:
        if not path.exists():
            raise FileNotFoundError(path)
        html = replace_script(html, src, path.read_text(encoding="utf-8"))

    output = dist / "laboratorio-har-real.html"
    output.write_text(html, encoding="utf-8")

    if re.search(r'<script\s+[^>]*src=', html, flags=re.IGNORECASE):
        raise RuntimeError("O bundle ainda contém scripts externos.")
    print(f"HTML offline salvo em {output} ({output.stat().st_size / 1024 / 1024:.2f} MiB)")


if __name__ == "__main__":
    main()
