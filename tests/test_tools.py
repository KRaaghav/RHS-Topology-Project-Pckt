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

import diagram                                      # noqa: E402
import floorplan                                    # noqa: E402
import labtest                                      # noqa: E402
import pktbuild                                     # noqa: E402
import pktconfig                                    # noqa: E402
import pktfile                                      # noqa: E402
import pktlayout                                    # noqa: E402

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


# ---------------------------------------------------------------- measurable tests of the lab

def test_lab_passes_every_measurable_test():
    result = labtest.run(LAB)
    failed = [t["title"] + ": " + "; ".join(t["detail"]) for t in result["tests"] if not t["passed"]]
    assert failed == []
    assert result["score"] == 100


def test_single_failure_test_really_breaks_things():
    picture = labtest.Picture(LAB)
    assert set(picture.hosts) <= picture.reach_isp()
    # a room switch is the one thing that has no backup: its own PCs are cut off
    alive = picture.reach_isp(dead_device="SW-E230")
    assert "E230-PC01" not in alive and "E110-PC01" in alive


def broken_copy(tmp_path, device, commands):
    copy = str(tmp_path / "broken.pkt")
    shutil.copy(LAB, copy)
    lab = pktconfig.Lab(copy)
    lab.set_config(device, pktconfig.merge(lab.config(device), commands)[0])
    lab.save()
    return {t["id"]: t for t in labtest.run(copy)["tests"]}


def test_wrong_vlan_on_a_port_is_found(tmp_path):
    tests = broken_copy(tmp_path, "SW-E230", "interface fa0/3\n switchport access vlan 20\n")
    assert not tests["host-vlans"]["passed"]
    assert "E230-PC03" in tests["host-vlans"]["detail"][0]
    assert tests["trunks"]["passed"]


def test_vlan_missing_on_a_trunk_is_found(tmp_path):
    tests = broken_copy(tmp_path, "DIST-L3-1", "interface gi1/0/6\n switchport trunk allowed vlan remove 20\n")
    assert not tests["trunks"]["passed"]
    assert tests["trunks"]["measured"] == tests["trunks"]["target"] - 1


# ---------------------------------------------------------------- adding a room, the picture

def test_room_is_added_to_a_copy_of_the_lab(tmp_path):
    copy = str(tmp_path / "bigger.pkt")
    shutil.copy(LAB, copy)
    before = labtest.Picture(copy)
    pktbuild.add_room("Z999", copy)
    after = labtest.Picture(copy)

    assert len(after.devices) == len(before.devices) + 17          # a switch and 16 PCs
    assert len(after.links) == len(before.links) + 18              # 16 PCs and two uplinks
    assert len(set(after.devices)) == len(after.devices)
    assert {other for other, port in after.cabled("SW-Z999").values() if other.startswith("DIST")} == \
        {"DIST-L3-1", "DIST-L3-2"}
    assert "hostname SW-Z999" in after.configs["SW-Z999"]
    assert set(after.hosts) <= after.reach_isp()
    # the tests that only look at cables and configs still pass with the new room
    tests = {t["id"]: t for t in labtest.run(copy)["tests"]}
    assert all(tests[name]["passed"] for name in ("single-failure", "two-uplinks", "trunks", "port-security"))


def test_bad_room_numbers_are_refused(tmp_path):
    with pytest.raises(pktconfig.Problem):
        pktbuild.add_room("room 12", LAB, write=False)
    with pytest.raises(pktconfig.Problem):
        pktbuild.add_room("E230", LAB, write=False)                # already there


def test_picture_shows_every_router_and_switch():
    picture = diagram.svg(LAB)
    for name in labtest.Picture(LAB).configs:
        assert f'data-name="{name}"' in picture
    with open(os.path.join(ROOT, "topology.svg")) as f:
        assert f.read() == picture                                 # the saved picture is up to date


def test_rooms_are_grouped_by_wing_and_floor():
    wings = pktlayout.wings()
    assert list(wings)[:3] == ["E", "C", "B"]
    assert wings["E"]["2"] == ["E203", "E230"]
    for wing, floors in wings.items():
        for floor, rooms in floors.items():
            assert all(room[0] == wing and room[1] == floor for room in rooms)


def test_nothing_on_the_canvas_overlaps():
    boxes = pktlayout.boxes()
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]), (a, b)
    places = list(pktlayout.positions().values())
    assert len(set(places)) == len(places)                         # no two devices on the same spot


def test_building_sketch_has_every_room_of_the_lab():
    sketch = floorplan.svg()
    for room in pktlayout.classrooms():
        assert f">SW-{room}<" in sketch
    with open(os.path.join(ROOT, "floorplan.svg")) as f:
        assert f.read() == sketch                                  # the saved sketch is up to date
