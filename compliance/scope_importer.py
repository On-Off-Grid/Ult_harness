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
from typing import List

from core.types import TargetScope, ScopeRule, ScopeMatchType, Platform


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

                match_type = (
                    ScopeMatchType.WILDCARD
                    if "*. " in identifier or identifier.startswith("*.")
                    else ScopeMatchType.EXACT
                )
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

            match_type = (
                ScopeMatchType.WILDCARD
                if "*. " in name or name.startswith("*.")
                else ScopeMatchType.EXACT
            )
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
