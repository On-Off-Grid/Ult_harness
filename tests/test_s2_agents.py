# tests/test_s2_agents.py  — S2.8: agents/specialists/ (16 specialists) + base + dual-session
"""All 16 specialist agents import, instantiate, and expose a valid category.

The plan's S2.8 wording (frontmatter / model field / tool refs) targets markdown
agent specs; in this Python codebase the faithful equivalent is: import +
instantiate + `category` resolves to a real VulnCategory + `scan` has the
contract signature. We verify that here.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

from agents import specialists as sp_pkg
from agents.specialist_base import DualSessionMixin, ISpecialist, OOBMixin
from core.types import VulnCategory

# The specialist modules (16). Explicit list — pkgutil.iter_modules is
# unreliable here because agents/specialists is a namespace package.
# A test below asserts this list still matches the directory on disk.
_SPECIALIST_MODULES = [
    "ai_jailbreak_specialist",
    "bac_specialist",
    "business_logic_specialist",
    "csti_specialist",
    "header_injection_specialist",
    "idor_specialist",
    "jwt_specialist",
    "lfi_specialist",
    "mass_assignment_specialist",
    "open_redirect_specialist",
    "prototype_pollution_specialist",
    "rce_specialist",
    "sqli_specialist",
    "ssrf_specialist",
    "xss_specialist",
    "xxe_specialist",
]


def _classes():
    """Map each specialist class to its module name."""
    out = {}
    for name in _SPECIALIST_MODULES:
        mod = importlib.import_module(f"agents.specialists.{name}")
        for _, obj in vars(mod).items():
            if isinstance(obj, type) and issubclass(obj, ISpecialist) and obj is not ISpecialist:
                out[obj.__name__] = (name, obj)
    return out


def test_all_sixteen_specialists_present():
    assert len(_SPECIALIST_MODULES) == 16, f"expected 16, got {_SPECIALIST_MODULES}"
    assert len(_classes()) == 16, "expected 16 instantiable specialist classes"
    # The list must still match what's actually on disk (catches renames/splits).
    from pathlib import Path
    on_disk = {p.stem for p in Path(sp_pkg.__path__[0]).iterdir()
               if p.suffix == ".py" and p.name != "__init__.py"}
    assert set(_SPECIALIST_MODULES) == on_disk, (
        f"list/disk mismatch: extra={set(_SPECIALIST_MODULES) - on_disk}, "
        f"missing={on_disk - set(_SPECIALIST_MODULES)}"
    )


def test_every_specialist_instantiates_and_has_category():
    seen_categories: set[str] = set()
    for cls_name, (mod_name, cls) in _classes().items():
        inst = cls()
        assert isinstance(inst, ISpecialist), f"{cls_name} not an ISpecialist"
        cat = inst.category
        assert isinstance(cat, VulnCategory), f"{cls_name}.category is {type(cat)}"
        seen_categories.add(cat.value)
        # scan() must be a coroutine with the contract signature.
        assert inspect.iscoroutinefunction(inst.scan)
        params = inspect.signature(inst.scan).parameters
        assert list(params) == ["target", "scope", "session_ctx", "correlation_id"], (
            f"{cls_name}.scan signature drifted: {list(params)}"
        )
    # All 16 specialists should map to distinct vulnerability categories.
    assert len(seen_categories) == 16, f"categories not unique: {sorted(seen_categories)}"


def test_category_covers_the_required_set():
    seen = {inst.category.value for inst in (cls() for _n, (_m, cls) in _classes().items())}
    # A few categories the harness is explicitly built to hunt.
    for required in ("sqli", "xss", "ssrf", "idor", "rce", "xxe", "jwt", "bac"):
        assert required in seen, f"missing specialist for category {required}"


def test_oob_mixin_classes_wire_an_oob_engine():
    oob_classes = [cls for _, (name, cls) in _classes().items()
                   if issubclass(cls, OOBMixin)]
    assert oob_classes, "expected at least one OOBMixin specialist"
    for cls in oob_classes:
        inst = cls()
        # OOBMixin stores an oob_engine attribute.
        assert hasattr(inst, "oob_engine")


def test_dual_session_mixin_classes():
    """The IDOR and BAC specialists are the DualSessionMixin users and wire a
    real DualSessionTester inside scan() (the mixin itself is a placeholder,
    so the meaningful check is on the subclasses)."""
    ds_classes = {name: cls for name, (mod_name, cls) in _classes().items()
                  if issubclass(cls, DualSessionMixin)}
    assert set(ds_classes) == {"IDORSpecialist", "BACSpecialist"}
    for name, cls in ds_classes.items():
        src = inspect.getsource(cls.scan)
        assert "DualSessionTester" in src, f"{name}.scan does not use DualSessionTester"
        assert "run_matrix" in src, f"{name}.scan does not call run_matrix"


def test_specialist_base_is_abstract():
    with pytest.raises(TypeError):
        ISpecialist()  # abstract: cannot instantiate directly


def test_ispecialist_declares_scan_and_category():
    assert "scan" in vars(ISpecialist)
    assert "category" in vars(ISpecialist)
    # scan must be abstract on the base.
    assert getattr(ISpecialist.scan, "__isabstractmethod__", False) or \
           "abstractmethod" in str(inspect.getsource(ISpecialist))
