#!/usr/bin/env python3
"""Convert an OpenAI ChatGPT data export into a directory of markdown files.

Usage:
    python3 convert.py <export-dir> <output-dir> [--skip-assets] [--verbose]

Requires Python 3.8+ and no external dependencies.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

def slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower()
    text = re.sub(r"[''`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "untitled"


def dedupe_filename(path: Path) -> Path:
    """Append -2, -3, … if *path* already exists."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    n = 2
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def ts_to_datetime(ts) -> datetime:
    """Convert a Unix timestamp (possibly None) to a datetime."""
    if ts is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# DAG traversal
# ---------------------------------------------------------------------------

def get_canonical_ids(mapping: dict, current_node: str) -> set:
    """Return the set of node IDs on the canonical (last-viewed) path."""
    ids = set()
    node_id = current_node
    while node_id:
        ids.add(node_id)
        node = mapping.get(node_id)
        if not node:
            break
        node_id = node.get("parent")
    return ids


def find_root(mapping: dict) -> str | None:
    """Find the root node (no parent) in the mapping."""
    for nid, node in mapping.items():
        if node.get("parent") is None:
            return nid
    return None


def walk_tree(mapping: dict, node_id: str, canonical_ids: set):
    """Depth-first walk yielding (message_or_none, is_branch_marker, info)."""
    node = mapping.get(node_id)
    if not node:
        return

    msg = node.get("message")
    if msg:
        yield msg, False, None

    children = node.get("children", [])
    if not children:
        return

    canonical = [c for c in children if c in canonical_ids]
    alternatives = [c for c in children if c not in canonical_ids]

    # Render canonical path first
    for c in canonical:
        yield from walk_tree(mapping, c, canonical_ids)

    # Render alternatives — only wrap in <details> if this is a true branch point
    if alternatives and canonical:
        for i, c in enumerate(alternatives):
            yield None, True, {"branch_start": True, "index": i + 2, "total": len(children)}
            yield from walk_tree(mapping, c, canonical_ids)
            yield None, True, {"branch_end": True}
    elif alternatives:
        # No canonical child at this node — just continue down the alt path
        for c in alternatives:
            yield from walk_tree(mapping, c, canonical_ids)


# ---------------------------------------------------------------------------
# Content renderers
# ---------------------------------------------------------------------------

def render_text(content: dict) -> str:
    parts = content.get("parts", [])
    texts = []
    for p in parts:
        if isinstance(p, str) and p.strip():
            texts.append(p)
    return "\n\n".join(texts)


def render_multimodal(content: dict, assets_map: dict) -> str:
    parts = content.get("parts", [])
    texts = []
    for p in parts:
        if isinstance(p, str):
            if p.strip():
                texts.append(p)
        elif isinstance(p, dict):
            ct = p.get("content_type")
            if ct == "image_asset_pointer":
                pointer = p.get("asset_pointer", "")
                asset_id = re.sub(r"^(sediment|file-service)://", "", pointer)
                meta = p.get("metadata") or {}
                dalle = meta.get("dalle") or {}
                alt = dalle.get("prompt") or "image"
                filename = assets_map.get(asset_id, asset_id)
                texts.append(f"![{alt}](../assets/{filename})")
            elif ct == "text" or ct is None:
                # Nested text part
                text = p.get("text", "")
                if text.strip():
                    texts.append(text)
    return "\n\n".join(texts)


def render_code(content: dict) -> str:
    lang = content.get("language") or ""
    if lang == "unknown":
        lang = ""
    text = content.get("text", "")
    if not text.strip():
        return ""
    return f"```{lang}\n{text}\n```"


def render_execution_output(content: dict) -> str:
    text = content.get("text", "")
    if not text.strip():
        return ""
    return (
        "<details><summary>Output</summary>\n\n"
        f"```\n{text}\n```\n\n"
        "</details>"
    )


def render_tether_quote(content: dict) -> str:
    text = content.get("text", "").strip()
    url = content.get("url", "")
    domain = content.get("domain", "")
    if not text:
        return ""
    quoted = "\n".join(f"> {line}" for line in text.split("\n"))
    source = ""
    if url and not url.startswith("file-"):
        source = f"\n> — [{domain}]({url})"
    elif domain:
        source = f"\n> — {domain}"
    return quoted + source


def render_sonic_webpage(content: dict) -> str:
    title = content.get("title", "")
    url = content.get("url", "")
    text = content.get("text", "").strip()
    if not text and not title:
        return ""
    parts = []
    if title and url:
        parts.append(f"> **[{title}]({url})**")
    elif title:
        parts.append(f"> **{title}**")
    if text:
        # Trim the sonic markup artifacts
        cleaned = re.sub(r"[\ue200-\ue2ff]\w*[\ue200-\ue2ff]?", "", text).strip()
        if cleaned:
            quoted = "\n".join(f"> {line}" for line in cleaned.split("\n"))
            parts.append(quoted)
    return "\n".join(parts) if parts else ""


def render_thoughts(content: dict) -> str:
    thoughts = content.get("thoughts", [])
    if not thoughts:
        return ""
    texts = []
    for t in thoughts:
        c = t.get("content", "").strip()
        if c:
            texts.append(c)
    if not texts:
        return ""
    body = "\n\n".join(texts)
    return (
        "<details><summary>Thinking...</summary>\n\n"
        f"{body}\n\n"
        "</details>"
    )


def render_reasoning_recap(content: dict) -> str:
    text = content.get("content", "").strip()
    if text:
        return f"*{text}*"
    return ""


def render_system_error(content: dict) -> str:
    name = content.get("name", "Error")
    text = content.get("text", "").strip()
    if text:
        return f"**{name}:** {text}"
    return f"**{name}**"


# Content types to skip entirely
SKIP_CONTENT_TYPES = {
    "tether_browsing_display",
    "user_editable_context",
    "computer_output",
    "app_pairing_content",
}


def render_message_content(content: dict, assets_map: dict) -> str:
    """Render a message's content dict to markdown. Returns empty string to skip."""
    ct = content.get("content_type", "text")

    if ct in SKIP_CONTENT_TYPES:
        return ""

    if ct == "text":
        return render_text(content)
    elif ct == "multimodal_text":
        return render_multimodal(content, assets_map)
    elif ct == "code":
        return render_code(content)
    elif ct == "execution_output":
        return render_execution_output(content)
    elif ct == "tether_quote":
        return render_tether_quote(content)
    elif ct == "sonic_webpage":
        return render_sonic_webpage(content)
    elif ct == "thoughts":
        return render_thoughts(content)
    elif ct == "reasoning_recap":
        return render_reasoning_recap(content)
    elif ct == "system_error":
        return render_system_error(content)
    else:
        # Unknown content type — render text parts if any
        return render_text(content)


# ---------------------------------------------------------------------------
# Conversation renderer
# ---------------------------------------------------------------------------

ROLE_HEADINGS = {
    "user": "## User",
    "assistant": "## Assistant",
}


def render_conversation(convo: dict, assets_map: dict) -> str | None:
    """Render a conversation dict to a markdown string. Returns None to skip."""
    mapping = convo.get("mapping", {})
    current_node = convo.get("current_node")

    if not mapping or not current_node:
        return None

    canonical_ids = get_canonical_ids(mapping, current_node)
    root = find_root(mapping)
    if not root:
        return None

    # Collect models used
    models_used = set()
    for nid, node in mapping.items():
        msg = node.get("message")
        if msg:
            m = msg.get("metadata", {}).get("model_slug")
            if m:
                models_used.add(m)

    # Build frontmatter
    title = convo.get("title") or "Untitled"
    create_time = convo.get("create_time") or convo.get("update_time")
    dt = ts_to_datetime(create_time)
    conv_id = convo.get("conversation_id", convo.get("id", ""))
    default_model = convo.get("default_model_slug", "")
    is_archived = convo.get("is_archived", False)

    # Count user/assistant messages
    message_count = 0
    for nid, node in mapping.items():
        msg = node.get("message")
        if msg:
            role = msg.get("author", {}).get("role")
            if role in ("user", "assistant"):
                message_count += 1

    models_list = sorted(models_used) if models_used else [default_model] if default_model else []

    lines = [
        "---",
        f'title: "{escape_yaml(title)}"',
        f"date: {format_iso(dt)}",
        f"conversation_id: {conv_id}",
    ]
    if default_model:
        lines.append(f"model: {default_model}")
    if models_list:
        lines.append(f"models_used: [{', '.join(models_list)}]")
    lines.append(f"message_count: {message_count}")
    lines.append(f"is_archived: {'true' if is_archived else 'false'}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")

    # Walk the tree and render messages
    body_parts = []
    last_role = None
    in_branch = False

    for msg, is_marker, info in walk_tree(mapping, root, canonical_ids):
        if is_marker:
            if info.get("branch_start"):
                idx = info["index"]
                total = info["total"]
                body_parts.append(
                    f"\n<details><summary>Alternative response (branch {idx} of {total})</summary>\n"
                )
                in_branch = True
            elif info.get("branch_end"):
                body_parts.append("\n</details>\n")
                in_branch = False
            continue

        role = msg.get("author", {}).get("role", "")
        content = msg.get("content", {})

        # Skip system messages
        if role == "system":
            continue

        # Skip visually hidden messages
        if msg.get("metadata", {}).get("is_visually_hidden_from_conversation"):
            continue

        rendered = render_message_content(content, assets_map)
        if not rendered.strip():
            continue

        # Tool messages render inline (no heading)
        if role == "tool":
            body_parts.append(rendered)
            body_parts.append("")
            continue

        heading = ROLE_HEADINGS.get(role)
        if heading and role != last_role:
            body_parts.append(heading)
            body_parts.append("")
            last_role = role

        body_parts.append(rendered)
        body_parts.append("")

    body = "\n".join(body_parts).strip()
    if not body:
        return None

    # Footer
    export_date = "2026-01-26"
    footer = f"\n\n---\n\n*Exported from ChatGPT on {export_date}*\n"

    return "\n".join(lines) + body + footer


def escape_yaml(s: str) -> str:
    """Escape a string for use in YAML double-quoted scalar."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Asset handling
# ---------------------------------------------------------------------------

def build_asset_index(export_dir: Path) -> dict[str, Path]:
    """Build a map of asset_id → file path on disk.

    Covers:
      - file_XXXXX-sanitized.{ext} (new naming)
      - file-XXXXX-*.{ext} (old naming with hyphen)
      - dalle-generations/*
    """
    index = {}

    for entry in export_dir.iterdir():
        name = entry.name
        if entry.is_file():
            # file_00000000...-sanitized.png
            if name.startswith("file_"):
                # Extract the ID (file_XXXX part before -sanitized or extension)
                base = name.split("-sanitized")[0] if "-sanitized" in name else name.rsplit(".", 1)[0]
                index[base] = entry
            # file-XXXXX-something.ext (old hyphen style)
            elif name.startswith("file-"):
                # The asset pointer may reference just the file-XXXX prefix
                # Extract the first component: file-<id>
                parts = name.split("-", 2)
                if len(parts) >= 2:
                    prefix = f"{parts[0]}-{parts[1]}"
                    index[prefix] = entry
                index[name.rsplit(".", 1)[0]] = entry

    # DALL-E generations
    dalle_dir = export_dir / "dalle-generations"
    if dalle_dir.is_dir():
        for entry in dalle_dir.iterdir():
            if entry.is_file():
                index[entry.stem] = entry

    return index


def collect_referenced_assets(convo: dict) -> set[str]:
    """Return set of asset IDs referenced by a conversation."""
    ids = set()
    mapping = convo.get("mapping", {})
    for nid, node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue
        content = msg.get("content", {})
        if content.get("content_type") == "multimodal_text":
            for part in content.get("parts", []):
                if isinstance(part, dict) and part.get("content_type") == "image_asset_pointer":
                    pointer = part.get("asset_pointer", "")
                    asset_id = re.sub(r"^(sediment|file-service)://", "", pointer)
                    if asset_id:
                        ids.add(asset_id)
        # Also check attachments
        attachments = msg.get("metadata", {}).get("attachments", [])
        if attachments:
            for att in attachments:
                att_id = att.get("id", "")
                if att_id:
                    ids.add(att_id)
    return ids


def copy_assets(
    referenced: set[str],
    asset_index: dict[str, Path],
    assets_dir: Path,
) -> dict[str, str]:
    """Copy referenced assets to assets_dir. Return asset_id → filename map."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for asset_id in referenced:
        src = asset_index.get(asset_id)
        if not src:
            continue
        dest = assets_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
        result[asset_id] = src.name
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert an OpenAI ChatGPT data export to markdown files."
    )
    parser.add_argument("export_dir", help="Path to extracted OpenAI export directory")
    parser.add_argument("output_dir", help="Path to write the markdown archive")
    parser.add_argument("--skip-assets", action="store_true", help="Don't copy image assets")
    parser.add_argument("--verbose", action="store_true", help="Print each conversation as processed")
    args = parser.parse_args()

    export_dir = Path(args.export_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    convos_json = export_dir / "conversations.json"
    if not convos_json.exists():
        print(f"Error: {convos_json} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {convos_json} ...")
    with open(convos_json, "r", encoding="utf-8") as f:
        conversations = json.load(f)

    print(f"Found {len(conversations)} conversations")

    # Build asset index
    if not args.skip_assets:
        print("Indexing assets ...")
        asset_index = build_asset_index(export_dir)
        print(f"Found {len(asset_index)} asset files")
    else:
        asset_index = {}

    convos_dir = output_dir / "conversations"
    assets_dir = output_dir / "assets"
    convos_dir.mkdir(parents=True, exist_ok=True)

    # Collect all referenced assets first (for a single copy pass)
    all_referenced = set()
    if not args.skip_assets:
        for convo in conversations:
            all_referenced |= collect_referenced_assets(convo)
        assets_map = copy_assets(all_referenced, asset_index, assets_dir)
        print(f"Copied {len(assets_map)} assets")
    else:
        assets_map = {}

    # Sort by create_time for deterministic output
    conversations.sort(key=lambda c: c.get("create_time") or 0)

    converted = 0
    skipped = 0
    used_paths = set()

    for i, convo in enumerate(conversations, 1):
        title = convo.get("title") or "Untitled"

        if args.verbose:
            print(f"[{i}/{len(conversations)}] {title}")

        md = render_conversation(convo, assets_map)
        if md is None:
            skipped += 1
            continue

        # Determine output path
        create_time = convo.get("create_time") or convo.get("update_time")
        dt = ts_to_datetime(create_time)
        year = str(dt.year)
        date_prefix = dt.strftime("%Y-%m-%d")
        slug = slugify(title)
        filename = f"{date_prefix}-{slug}.md"

        year_dir = convos_dir / year
        year_dir.mkdir(parents=True, exist_ok=True)

        out_path = dedupe_filename(year_dir / filename)
        # Also track in-memory to handle sorting ties
        while out_path in used_paths:
            out_path = dedupe_filename(out_path)
        used_paths.add(out_path)

        out_path.write_text(md, encoding="utf-8")
        converted += 1

    print(f"\nDone: {converted} converted, {skipped} skipped")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
