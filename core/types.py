from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime


class Platform(str, Enum):
    HACKERONE = "hackerone"
    BUGCROWD = "bugcrowd"
    YESWEHACK = "yeswehack"
    INTIGRITI = "intigriti"
    IMMUNEFI = "immunefi"


class ScopeMatchType(str, Enum):
    EXACT = "exact"           # app.example.com
    WILDCARD = "wildcard"     # *.example.com
    CIDR = "cidr"             # 10.0.0.0/8
    REGEX = "regex"           # ^api\d+\.example\.com$


class VulnCategory(str, Enum):
    SQLI = "sqli"
    XSS = "xss"
    SSRF = "ssrf"
    IDOR = "idor"
    LFI = "lfi"
    RCE = "rce"
    XXE = "xxe"
    JWT = "jwt"
    OPEN_REDIRECT = "open_redirect"
    PROTOTYPE_POLLUTION = "prototype_pollution"
    CSTI = "csti"
    MASS_ASSIGNMENT = "mass_assignment"
    HEADER_INJECTION = "header_injection"
    BAC = "bac"
    AI_JAILBREAK = "ai_jailbreak"
    BUSINESS_LOGIC = "business_logic"


class VulnStatus(str, Enum):
    IDENTIFIED = "identified"
    VALIDATING = "validating"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    CHAINED = "chained"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass
class ScopeRule:
    pattern: str
    match_type: ScopeMatchType
    description: str = ""


@dataclass
class TargetScope:
    program_handle: str
    platform: Platform
    in_scope: List[ScopeRule] = field(default_factory=list)
    out_of_scope: List[ScopeRule] = field(default_factory=list)
    rate_limit_rps: float = 10.0
    max_concurrent: int = 5


@dataclass
class PlatformHeaders:
    headers: Dict[str, str] = field(default_factory=dict)
    user_agent: str = ""

    @classmethod
    def for_platform(cls, platform: Platform, username: str) -> "PlatformHeaders":
        header_map = {
            Platform.HACKERONE:  {"X-BugBounty-HackerOne": username},
            Platform.BUGCROWD:  {"X-Bugcrowd-Researcher": username},
            Platform.YESWEHACK: {"X-YesWeHack-User": username},
            Platform.INTIGRITI: {"X-Intigriti-Researcher": username},
            Platform.IMMUNEFI:  {"X-Immunefi-Researcher": username},
        }
        return cls(
            headers=header_map.get(platform, {}),
            user_agent=f"Mozilla/5.0 (BugBounty; {platform.value}/{username})"
        )


@dataclass
class MultiSessionContext:
    user_a_headers: Dict[str, str] = field(default_factory=dict)
    user_b_headers: Dict[str, str] = field(default_factory=dict)
    admin_headers: Dict[str, str] = field(default_factory=dict)
    unauth_headers: Dict[str, str] = field(default_factory=dict)
    session_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenBudget:
    warning_threshold: int = 50_000
    hard_cap: int = 100_000
    tokens_used: int = 0
    cost_usd: float = 0.0

    @property
    def remaining(self) -> int:
        return max(0, self.hard_cap - self.tokens_used)

    @property
    def is_exhausted(self) -> bool:
        return self.tokens_used >= self.hard_cap


@dataclass
class Task:
    task_id: str
    wing_id: str
    specialist_id: str
    correlation_id: str
    target_endpoint: str
    vuln_category: VulnCategory
    status: VulnStatus = VulnStatus.IDENTIFIED
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestrationEvent:
    event_type: str           # e.g. "validation_started", "finding_confirmed", "budget_warning"
    correlation_id: str
    source_component: str     # e.g. "sqli_specialist", "triage_controller"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = field(default_factory=dict)

