"""Tests for clipboard read + helpers (subprocess mocked; no X, no xclip needed)."""
import subprocess

import pytest

from i3_cua_mcp import clipboard


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["xclip"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_read_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(0, stdout="cfut_ABC"))
    assert clipboard.read_clipboard() == "cfut_ABC"


def test_read_returns_empty_on_nonzero(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(1, stderr="no owner"))
    assert clipboard.read_clipboard() == ""


def test_read_passes_selection(monkeypatch):
    seen = {}
    monkeypatch.setattr(clipboard, "_run",
                        lambda args, **kw: seen.update(args=args) or _completed(0, "x"))
    clipboard.read_clipboard("primary")
    assert seen["args"] == ["-selection", "primary", "-o"]


def test_read_rejects_invalid_selection():
    with pytest.raises(ValueError):
        clipboard.read_clipboard("middle")


def test_run_sets_a_timeout(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return _completed(0, "ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    clipboard._run(["-selection", "clipboard", "-o"])
    assert seen.get("timeout")


def test_run_raises_when_xclip_missing(monkeypatch):
    def missing(argv, **kw):
        raise FileNotFoundError("no xclip")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(clipboard.ClipboardError):
        clipboard._run(["-selection", "clipboard", "-o"])
