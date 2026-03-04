# chatgpt-export

Convert an OpenAI ChatGPT data export into clean, searchable markdown files.

A single Python script. No dependencies. Download it and run it.

## Quick start

```bash
# Download
curl -sLO https://raw.githubusercontent.com/johnx25bd/chatgpt-export/main/convert.py

# Convert your export
python3 convert.py ~/Downloads/openai-export ~/Documents/chatgpt-archive
```

Requires Python 3.8+, stdlib only.

## What it does

Takes the `conversations.json` from an [OpenAI data export](https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data) and produces:

```
<output-dir>/
  conversations/
    2023/
      2023-01-29-project-kickoff-notes.md
      2023-02-14-api-design-review.md
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
title: "API Design Review"
date: 2024-03-15T10:23:44
conversation_id: abc123-def456
model: gpt-4o
models_used: [gpt-4, gpt-4o]
message_count: 18
is_archived: false
---

# API Design Review

## User

Can you review this API design?

## Assistant

Looking at the endpoint structure...
```

## Usage

```
python3 convert.py <export-dir> <output-dir> [--skip-assets] [--verbose]
```

| Argument | Description |
|---|---|
| `export-dir` | Path to extracted OpenAI export (the directory containing `conversations.json`) |
| `output-dir` | Where to write the markdown archive (any path you want) |
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

## Export format variability

This script was built against an OpenAI export from January 2026. OpenAI doesn't document the export format, and it has changed over time. If the script doesn't work with your export, the structure may differ.

The core data lives in `conversations.json` — an array of conversation objects. Each conversation has a `mapping` field containing a DAG of message nodes with `parent`/`children` pointers, and a `current_node` pointing to the leaf of the canonical path.

**If you need to adapt the script for a different export format**, point a coding agent at your export and this script:

```
I have a ChatGPT data export at <path-to-export>. I want to convert it to
markdown using this script: <path-to-convert.py>

The script was written for a January 2026 export format. My export may differ.

1. Read convert.py to understand the expected format
2. Read my conversations.json (sample a few conversations) to understand
   my actual format
3. Identify the differences and update the script to handle my export

Run the updated script and verify the output looks correct.
```

## Limitations

- No audio transcription — `.wav` files from voice conversations are not processed
- No incremental updates — re-running overwrites existing files in the output directory
- Export format is reverse-engineered; OpenAI may change it at any time

## License

MIT
