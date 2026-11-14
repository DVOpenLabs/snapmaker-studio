"""The link walk in localpath, exercised with simulated links so it runs on accounts that cannot create symlinks.

Evidence label: fixture-tested.
"""
from __future__ import annotations

import os
import stat

from snapstudio_core import localpath

UNC = "\\\\attacker-host\\share\\p.3mf"


class _Link:
    st_mode = stat.S_IFLNK


def _simulate(monkeypatch, link: str, target: str):
    real_lstat = os.lstat

    def fake_lstat(path, *a, **k):
        return _Link() if path == link else real_lstat(path, *a, **k)

    def fake_readlink(path, *a, **k):
        if path == link:
            return target
        raise OSError("not a link")

    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os, "readlink", fake_readlink)


def test_link_to_a_network_path_is_refused(monkeypatch, tmp_path):
    link = str(tmp_path / "linked.3mf")
    _simulate(monkeypatch, link, UNC)
    assert localpath._reaches_network(link) is True
    assert localpath.usable_path(link) is None


def test_link_to_a_mixed_separator_network_path_is_refused(monkeypatch, tmp_path):
    link = str(tmp_path / "linked.3mf")
    _simulate(monkeypatch, link, "/\\attacker-host/share/p.3mf")
    assert localpath._reaches_network(link) is True


def test_link_to_a_local_path_is_followed_and_allowed(monkeypatch, tmp_path):
    link = str(tmp_path / "linked.3mf")
    _simulate(monkeypatch, link, str(tmp_path / "real.3mf"))
    assert localpath._reaches_network(link) is False


def test_a_link_loop_is_refused(monkeypatch, tmp_path):
    link = str(tmp_path / "loop.3mf")
    _simulate(monkeypatch, link, link)
    assert localpath._reaches_network(link) is True
