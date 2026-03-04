# chatgpt-export

Convert an OpenAI ChatGPT data export into clean, searchable markdown files.

A single Python script. No dependencies. Download it and run it.

## Quick start

```bash
# Download
curl -sLO https://raw.githubusercontent.com/johnx25bd/chatgpt-export/main/convert.py

# Run
python3 convert.py ~/Downloads/2026-01-26-10-40-37-openai-export ./archive
```

Requires Python 3.8+, stdlib only.

## What it does

Takes the `conversations.json` from an [OpenAI data export](https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data) and produces:

```
archive/
  conversations/
    2023/
      2023-01-29-thought-leader-monitoring.md
      2023-02-14-london-re-investment-guide.md
    2024/
      ...
    2025/
      ...
  assets/
    file_0000000056e871f5b1e6d0a82620376e-sanitized.png
    ...
```

Each conversation becomes a markdown file with YAML frontmatter:

```markdown
---
title: "CV Feedback for Product Roles"
date: 2026-01-19T14:29:06
conversation_id: 696e3f8b-5394-8327-9dcc-c5521566820f
model: gpt-5-2
models_used: [gpt-5-2]
message_count: 10
is_archived: false
---

# CV Feedback for Product Roles

## User

Here's a CV — can you give me some feedback?

## Assistant

I'll take this as a serious positioning exercise...
```

## Usage

```
python3 convert.py <export-dir> <output-dir> [--skip-assets] [--verbose]
```

| Argument | Description |
|---|---|
| `export-dir` | Path to extracted OpenAI export (the directory containing `conversations.json`) |
| `output-dir` | Where to write the markdown archive |
| `--skip-assets` | Don't copy image/file assets (faster, smaller output) |
| `--verbose` | Print each conversation as it's processed |

## How it works

### DAG traversal

ChatGPT conversations are stored as a DAG (directed acyclic graph) of message nodes, not a flat list. Each time you edit a message or regenerate a response, the conversation branches. `current_node` points to the leaf of the path you last viewed.

The converter traces the canonical path (what you saw) and renders it normally. Alternative branches (edits, regenerations) are preserved in collapsible `<details>` blocks.

### Content types

| Content type | Rendering |
|---|---|
| `text` | Markdown text |
| `multimodal_text` | Text + `![image](../assets/filename.ext)` |
| `code` | Fenced code block with language |
| `execution_output` | Collapsible code block |
| `tether_quote` | Blockquote with source |
| `sonic_webpage` | Blockquote with title + URL |
| `thoughts` | Collapsible thinking block |
| `reasoning_recap` | Italic note (*Thought for 4 seconds*) |
| `system_error` | Error note |
| `tether_browsing_display` | Skipped |
| `user_editable_context` | Skipped (custom instructions) |
| `computer_output` | Skipped |
| `app_pairing_content` | Skipped |

### Roles

- `user` → `## User`
- `assistant` → `## Assistant`
- `system` → skipped (injected context, custom instructions)
- `tool` → rendered inline under the preceding assistant message

### Assets

Image references in conversations (`sediment://` and `file-service://` pointers) are resolved to actual files in the export and copied to `assets/`. Markdown image links use relative paths so everything works locally.

## Limitations

- No audio transcription — `.wav` files from voice conversations are not processed
- No incremental updates — re-running overwrites the output directory
- Export format is reverse-engineered from a January 2026 export; OpenAI may change the format

## License

MIT
