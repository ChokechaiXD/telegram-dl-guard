# -*- coding: utf-8 -*-
"""
Rule Engine — declarative condition→action rules for file processing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("guard.rules")

_RULES_FILE = Path("rules.yaml")


def parse_size(size_val: Any) -> int | None:
    """Parse size strings (e.g. '10MB', '500KB', '1.5GB') into bytes."""
    if size_val is None:
        return None
    if isinstance(size_val, int):
        return size_val
    s = str(size_val).strip().lower()
    if not s:
        return None
    
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)?$", s)
    if not m:
        try:
            return int(size_val)
        except (ValueError, TypeError):
            return None
            
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "kb":
        return int(num * 1024)
    elif unit == "mb":
        return int(num * 1024 * 1024)
    elif unit == "gb":
        return int(num * 1024 * 1024 * 1024)
    elif unit == "tb":
        return int(num * 1024 * 1024 * 1024 * 1024)
    return int(num)


@dataclass
class RuleCondition:
    sender: str | None = None
    sender_contains: str | None = None
    filename_regex: str | None = None
    media_type: str | None = None
    file_size_gt: int | None = None  # bytes
    file_size_lt: int | None = None  # bytes
    source_group: str | None = None


@dataclass
class RuleAction:
    skip: bool = False
    tag: str | None = None
    album: bool = False
    priority: bool = False
    move_to: str | None = None


@dataclass
class Rule:
    name: str
    condition: RuleCondition
    action: RuleAction
    enabled: bool = True


def load_rules(path: Path | None = None) -> list[Rule]:
    """Load rules from YAML file. Returns empty list if file missing."""
    p = path or _RULES_FILE
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        rules_data = data.get("rules", [])
        if not rules_data:
            return []
        rules = []
        for r in rules_data:
            if not r.get("enabled", True):
                continue
            cond_data = r.get("when", {})
            cond = RuleCondition(
                sender=cond_data.get("sender"),
                sender_contains=cond_data.get("sender_contains"),
                filename_regex=cond_data.get("filename_regex"),
                media_type=cond_data.get("media_type"),
                file_size_gt=parse_size(cond_data.get("file_size_gt")),
                file_size_lt=parse_size(cond_data.get("file_size_lt")),
                source_group=cond_data.get("source_group"),
            )
            act_data = r.get("action", {})
            action = RuleAction(
                skip=act_data.get("skip", False),
                tag=act_data.get("tag"),
                album=act_data.get("album", False),
                priority=act_data.get("priority", False),
                move_to=act_data.get("move_to"),
            )
            rules.append(Rule(name=r.get("name", "unnamed"), condition=cond, action=action))
        log.info("Loaded %d rules from %s", len(rules), p)
        return rules
    except Exception as e:
        log.warning("Could not load rules from %s: %s", p, e)
        return []


def compile_rules(rules: list[Rule]) -> list[tuple[Rule, re.Pattern | None]]:
    """Pre-compile regex patterns for performance."""
    compiled = []
    for rule in rules:
        pattern = None
        if rule.condition.filename_regex:
            try:
                pattern = re.compile(rule.condition.filename_regex, re.IGNORECASE)
            except re.error as e:
                log.warning("Invalid regex in rule '%s': %s", rule.name, e)
                continue
        compiled.append((rule, pattern))
    return compiled


def evaluate_rules(
    compiled_rules: list[tuple[Rule, re.Pattern | None]],
    sender: str,
    filename: str,
    media_type: str,
    file_size: int,
    source_group: str,
) -> RuleAction | None:
    """Evaluate all rules against a file. Returns first matching action or None."""
    normalized_sender = str(sender).lower().strip()
    normalized_media = str(media_type).lower().strip()
    normalized_group = str(source_group).lower().strip()

    for rule, pattern in compiled_rules:
        c = rule.condition

        # Check each condition with safe string conversions to prevent crash on non-string inputs
        if c.sender and str(c.sender).lower().strip() != normalized_sender:
            continue
        if c.sender_contains and str(c.sender_contains).lower().strip() not in normalized_sender:
            continue
        if c.filename_regex and pattern and not pattern.search(filename):
            continue
        if c.media_type and str(c.media_type).lower().strip() != normalized_media:
            continue
        if c.source_group and str(c.source_group).lower().strip() != normalized_group:
            continue
        if c.file_size_gt is not None and file_size <= c.file_size_gt:
            continue
        if c.file_size_lt is not None and file_size >= c.file_size_lt:
            continue

        # All conditions matched
        log.info("Rule '%s' matched: %s", rule.name, filename)
        return rule.action

    return None


def move_to_folder(filepath: Path, folder: str) -> Path:
    """Generate new path inside target folder, preserving filename."""
    target_dir = Path(folder) / filepath.parent.name
    return target_dir / filepath.name
