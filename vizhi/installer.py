"""Install / uninstall the vizhi PostToolUse hook in Claude Code's settings.json.

The hook entry follows Claude Code's settings schema:

    {
      "hooks": {
        "PostToolUse": [
          {
            "matcher": "*",
            "hooks": [
              { "type": "command", "command": "python -m vizhi.hook_receiver" }
            ]
          }
        ]
      }
    }

All settings.json content outside the vizhi entry is preserved verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOOK_EVENT = "PostToolUse"
HOOK_MATCHER = "*"
HOOK_TYPE = "command"
HOOK_COMMAND = "python -m vizhi.hook_receiver"

# TODO(v2.3): support a custom interpreter / venv path instead of bare `python`.
# TODO(v2.3): support PreToolUse install when blocking is implemented.
# TODO(v2.4): read install target (user vs. project settings) from a flag.


def get_settings_path() -> Path:
    """Return the absolute path to the user's Claude Code settings.json.

    Resolves `~/.claude/settings.json` against the current user's home directory
    on all platforms (Windows, macOS, Linux).
    """
    return Path.home() / ".claude" / "settings.json"


def load_settings(path: Path) -> dict[str, Any]:
    """Read settings.json from `path`. Return {} if the file does not exist.

    Raises json.JSONDecodeError if the file exists but is not valid JSON — the
    caller is expected to surface that to the user rather than silently clobber.
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"settings.json at {path} is valid JSON but not an object "
            f"(got {type(data).__name__}) — refusing to overwrite."
        )
    return data


def save_settings(path: Path, settings: dict[str, Any]) -> None:
    """Write `settings` back to `path` as pretty-printed JSON.

    Creates the parent directory if missing. Uses 2-space indent and a trailing
    newline so the file plays nicely with text editors and git diffs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def install_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Add the vizhi PostToolUse hook to `settings`.

    Returns `(updated_settings, already_installed)`. If the vizhi command is
    already present anywhere under PostToolUse, the dict is returned unchanged
    and the bool is True. Otherwise the hook is added and the bool is False.
    """
    hooks_root = settings.setdefault("hooks", {})
    if not isinstance(hooks_root, dict):
        raise ValueError(
            f"settings.hooks is not an object (got {type(hooks_root).__name__})."
        )

    post_tool_use = hooks_root.setdefault(HOOK_EVENT, [])
    if not isinstance(post_tool_use, list):
        raise ValueError(
            f"settings.hooks.{HOOK_EVENT} is not a list "
            f"(got {type(post_tool_use).__name__})."
        )

    if _vizhi_hook_present(post_tool_use):
        return settings, True

    post_tool_use.append(_vizhi_matcher_entry())
    return settings, False


def uninstall_hook(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove the vizhi PostToolUse hook from `settings`.

    Returns `(updated_settings, was_removed)`. Removes any inner hook whose
    command matches HOOK_COMMAND, then prunes empty matcher entries, empty
    PostToolUse lists, and an empty top-level `hooks` block. Returns False if
    no vizhi entry was found.
    """
    hooks_root = settings.get("hooks")
    if not isinstance(hooks_root, dict):
        return settings, False

    post_tool_use = hooks_root.get(HOOK_EVENT)
    if not isinstance(post_tool_use, list):
        return settings, False

    removed = False
    pruned_matchers: list[dict[str, Any]] = []
    for matcher_entry in post_tool_use:
        if not isinstance(matcher_entry, dict):
            pruned_matchers.append(matcher_entry)
            continue
        inner = matcher_entry.get("hooks")
        if not isinstance(inner, list):
            pruned_matchers.append(matcher_entry)
            continue
        kept_inner = [h for h in inner if not _is_vizhi_hook(h)]
        if len(kept_inner) != len(inner):
            removed = True
        if kept_inner:
            matcher_entry["hooks"] = kept_inner
            pruned_matchers.append(matcher_entry)
        # else: drop the matcher entry entirely (empty after removal)

    if pruned_matchers:
        hooks_root[HOOK_EVENT] = pruned_matchers
    else:
        hooks_root.pop(HOOK_EVENT, None)

    if not hooks_root:
        settings.pop("hooks", None)

    return settings, removed


def _vizhi_matcher_entry() -> dict[str, Any]:
    """Build the matcher entry that wraps the vizhi command hook."""
    return {
        "matcher": HOOK_MATCHER,
        "hooks": [
            {"type": HOOK_TYPE, "command": HOOK_COMMAND},
        ],
    }


def _vizhi_hook_present(post_tool_use: list[Any]) -> bool:
    """Return True if any matcher entry already contains the vizhi command."""
    for matcher_entry in post_tool_use:
        if not isinstance(matcher_entry, dict):
            continue
        inner = matcher_entry.get("hooks")
        if not isinstance(inner, list):
            continue
        if any(_is_vizhi_hook(h) for h in inner):
            return True
    return False


def _is_vizhi_hook(entry: Any) -> bool:
    """Return True if `entry` is a hook dict whose command runs vizhi."""
    if not isinstance(entry, dict):
        return False
    return entry.get("command") == HOOK_COMMAND
