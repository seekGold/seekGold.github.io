from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "site-index.js"


def iter_html_files():
    for path in sorted(ROOT.rglob("*.html")):
        if path == ROOT / "index.html":
            continue
        yield path


def build_entries():
    entries = []
    for path in iter_html_files():
        relative_path = path.relative_to(ROOT).as_posix()
        entries.append(
            {
                "path": relative_path,
                "name": path.name,
                "folder": path.parent.relative_to(ROOT).as_posix(),
            }
        )
    return entries


def render(entries):
    lines = ["window.SEEK_GOLD_FILE_INDEX = ["]
    for entry in entries:
        lines.append(
            '  {{ path: "{path}", name: "{name}", folder: "{folder}" }},'.format(
                path=entry["path"],
                name=entry["name"],
                folder=entry["folder"],
            )
        )
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
    lines.append("];")
    lines.append("")
    return "\n".join(lines)


def main():
    entries = build_entries()
    OUTPUT.write_text(render(entries), encoding="utf-8")
    print(f"Updated {OUTPUT.name} with {len(entries)} entries")


if __name__ == "__main__":
    main()
