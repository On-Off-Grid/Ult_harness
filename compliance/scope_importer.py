# compliance/scope_importer.py
"""
ScopeImporter: convert platform scope exports into a unified TargetScope.

Implements:
- parse_hackerone_csv(path, program_handle) -> TargetScope
- parse_bugcrowd_json(path, program_handle) -> TargetScope

Stubs for future platforms (YesWeHack, Intigriti) can be added later.
"""

import csv
import json
import re
from typing import List

from core.types import TargetScope, ScopeRule, ScopeMatchType, Platform


def _match_type_from_name(name: str) -> ScopeMatchType:
    """Infer a rule's match type from its pattern shape.

    The Bugcrowd JSON format carries no explicit match-type field, so this
    heuristic is the only signal. It must stay in sync with the output of
    `scripts/fetch_intigriti_scope.py` (which pre-shapes patterns for it):

    * regex syntax anywhere (`(y|ie)`, classes, anchors) -> REGEX
    * IP / CIDR only (`1.2.3.4`, `10.0.0.0/8`, `1.2.3.4/32`) -> CIDR
    * leading `*` in any position (`*.x`, `*dev.x`, `*idp*.x`) -> WILDCARD
    * anything else -> EXACT
    """
    if re.search(r"[()|{}[\]\\^$]", name):
        return ScopeMatchType.REGEX
    if re.fullmatch(r"[0-9.]+(?:/\d+)?", name):
        return ScopeMatchType.CIDR
    if name.startswith("*"):
        return ScopeMatchType.WILDCARD
    return ScopeMatchType.EXACT


class ScopeImporter:
    """Parses platform-specific scope export files into unified TargetScope."""

    @staticmethod
    def parse_hackerone_csv(file_path: str, program_handle: str) -> TargetScope:
        in_scope: List[ScopeRule] = []
        out_of_scope: List[ScopeRule] = []

        with open(file_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                identifier = (row.get("asset_identifier") or "").strip()
                asset_type = (row.get("asset_type") or "").strip()
                eligible = (row.get("eligible_for_bounty") or "true").lower() == "true"

                match_type = _match_type_from_name(identifier)
                rule = ScopeRule(
                    pattern=identifier,
                    match_type=match_type,
                    description=asset_type,
                )
                (in_scope if eligible else out_of_scope).append(rule)

        return TargetScope(
            program_handle=program_handle,
            platform=Platform.HACKERONE,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
        )

    @staticmethod
    def parse_bugcrowd_json(file_path: str, program_handle: str) -> TargetScope:
        in_scope: List[ScopeRule] = []
        out_of_scope: List[ScopeRule] = []

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for target in data.get("targets", []):
            name = target.get("name", "") or ""
            category = target.get("category", "") or ""
            in_scope_flag = target.get("in_scope", True)

            # Trust an explicit match_type (hand-edited or platform-specific
            # exports); otherwise infer from the pattern shape.
            explicit = (target.get("match_type") or "").strip().lower()
            match_type = (ScopeMatchType(explicit)
                          if explicit in {m.value for m in ScopeMatchType}
                          else _match_type_from_name(name))
            rule = ScopeRule(
                pattern=name,
                match_type=match_type,
                description=category,
            )
            (in_scope if in_scope_flag else out_of_scope).append(rule)

        return TargetScope(
            program_handle=program_handle,
            platform=Platform.BUGCROWD,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
        )

    @staticmethod
    def parse_yeswehack_json(file_path: str, program_handle: str) -> TargetScope:
        """Placeholder for YesWeHack exporter."""
        raise NotImplementedError("YesWeHack scope importer not implemented yet.")

    @staticmethod
    def parse_intigriti_json(file_path: str, program_handle: str) -> TargetScope:
        """Placeholder for Intigriti exporter."""
        raise NotImplementedError("Intigriti scope importer not implemented yet.")
