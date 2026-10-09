"""
Tests for the programs in tools/. GitHub runs these on every push (see
.github/workflows). To run them yourself:

  pip install pytest
  pytest

None of the tests change the real lab file. The one that writes works on a copy.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pktconfig                                    # noqa: E402
import pktfile                                      # noqa: E402

LAB = os.path.join(ROOT, "RHS School Network.pkt")


# ---------------------------------------------------------------- the .pkt file

def test_lab_opens_and_packs_back_the_same():
    with open(LAB, "rb") as f:
        raw = f.read()
    xml = pktfile.decode(raw)
    assert xml.startswith(b"<PACKETTRACER5")
    assert pktfile.decode(pktfile.encode(xml)) == xml


def test_damaged_file_is_refused():
    with open(LAB, "rb") as f:
        raw = bytearray(f.read())
    raw[100] ^= 1
    with pytest.raises(ValueError):
        pktfile.decode(bytes(raw))


def test_lab_matches_the_configs_folder():
    assert pktconfig.check(LAB) == 0


# ---------------------------------------------------------------- small helpers

def test_interface_names():
    assert pktconfig.full_interface("fa0/5") == "FastEthernet0/5"
    assert pktconfig.full_interface("gi1/0/3") == "GigabitEthernet1/0/3"
    assert pktconfig.full_interface("vlan 99") == "Vlan99"
    with pytest.raises(pktconfig.Problem):
        pktconfig.full_interface("banana")


def test_interface_range():
    assert pktconfig.interface_range("fa0/1 - 3 , fa0/7") == [
        "FastEthernet0/1", "FastEthernet0/2", "FastEthernet0/3", "FastEthernet0/7"]
    with pytest.raises(pktconfig.Problem):
        pktconfig.interface_range("fa0/5 - 2")


def test_vlan_lists():
    assert pktconfig.number_list("10,20,30-32") == {10, 20, 30, 31, 32}
    assert pktconfig.list_text({10, 20, 30, 31, 32}) == "10,20,30-32"
    with pytest.raises(pktconfig.Problem):
        pktconfig.number_list("5000")


def test_secret_hash_looks_like_ios():
    first = pktconfig.secret_hash("cisco")
    assert first.startswith("$1$mERr$")
    assert first == pktconfig.secret_hash("cisco")
    assert first != pktconfig.secret_hash("class")


# ---------------------------------------------------------------- merging commands into a config

CONFIG = [
    "hostname SW-TEST",
    "!",
    "interface FastEthernet0/1",
    " description old text",
    " switchport access vlan 10",
    " switchport mode access",
    "!",
    "interface FastEthernet0/2",
    " switchport mode access",
    "!",
    "end",
]


def test_new_value_replaces_the_old_one():
    lines, _, _ = pktconfig.merge(CONFIG, "interface fa0/1\n description new text\n")
    assert " description new text" in lines
    assert " description old text" not in lines
    assert " switchport access vlan 10" in lines


def test_no_takes_a_line_out():
    lines, _, _ = pktconfig.merge(CONFIG, "interface fa0/1\n no description\n")
    assert not any(l.startswith(" description") for l in lines)


def test_interface_range_changes_every_port():
    lines, _, _ = pktconfig.merge(CONFIG, "interface range fa0/1 - 2\n switchport access vlan 30\n")
    assert lines.count(" switchport access vlan 30") == 2
    assert " switchport access vlan 10" not in lines


def test_hostname_and_vlan():
    lines, vlans, _ = pktconfig.merge(CONFIG, "hostname SW-NEW\nvlan 70\n name ROBOTICS\n")
    assert "hostname SW-NEW" in lines
    assert "hostname SW-TEST" not in lines
    assert ("add", 70, "ROBOTICS") in vlans


def test_port_that_does_not_exist_is_a_problem():
    with pytest.raises(pktconfig.Problem):
        pktconfig.merge(CONFIG, "interface fa0/9\n shutdown\n")


def test_show_commands_are_refused():
    with pytest.raises(pktconfig.Problem):
        pktconfig.merge(CONFIG, "show running-config\n")


def test_merge_leaves_the_original_alone():
    before = list(CONFIG)
    pktconfig.merge(CONFIG, "interface fa0/1\n shutdown\n")
    assert CONFIG == before


# ---------------------------------------------------------------- writing into a lab

def test_change_is_written_into_a_copy_of_the_lab(tmp_path):
    copy = str(tmp_path / "copy.pkt")
    shutil.copy(LAB, copy)
    lab = pktconfig.Lab(copy)
    name = lab.names()[0]
    lines, _, _ = pktconfig.merge(lab.config(name), "banner motd #pytest was here#\n")
    lab.set_config(name, lines)
    lab.save()

    again = pktconfig.Lab(copy)
    assert any("pytest was here" in l for l in again.config(name))
    others = [n for n in again.names() if n != name]
    original = pktconfig.Lab(LAB)
    assert all(again.config(n) == original.config(n) for n in others)
