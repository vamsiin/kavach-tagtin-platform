"""Upload CSV / Excel for the Elements, Tags and TINs registers: preview first, then
apply only when no row has an error."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_register_crud import client, _make_admin_designer_checker  # noqa: F401 (fixture)


def _setup(client):
    admin, des, chk = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "Aler", "kavach_station_id": "103", "centre_line_m": 262750},
                      headers=des).json()["id"]
    for name, lo, hi in [("DN MAIN", 259740, 265279), ("UP MAIN", 258024, 266417), ("COMMON LOOP", 262175, 263146)]:
        client.post(f"/stations/{sid}/tracks", json={"name": name, "track_type": "Main", "start_m": lo, "end_m": hi},
                    headers=des)
    return sid, des, chk


def _up(client, sid, kind, text, h, apply=False, update=False, name="x.csv"):
    return client.post(f"/stations/{sid}/registers/{kind}/import",
                       params={"apply": str(apply).lower(), "update_existing": str(update).lower()},
                       files={"file": (name, text if isinstance(text, bytes) else text.encode(), "text/csv")}, headers=h)


def test_templates_import_cleanly(client):
    sid, des, _ = _setup(client)
    for kind in ("elements", "tags", "tins"):
        t = client.get(f"/stations/{sid}/registers/{kind}/template", headers=des)
        assert t.status_code == 200 and "attachment" in t.headers["content-disposition"]
        r = _up(client, sid, kind, t.text, des, apply=True)
        assert r.status_code == 200, r.text
        assert r.json()["applied"] and r.json()["counts"]["error"] == 0


def test_elements_preview_errors_then_apply(client):
    sid, des, chk = _setup(client)
    bad = ("Ref,Type,Chainage (m),Line,To line\n"
           "S1,Main Home without Junction Route Indicator,261789,DN MAIN,\n"
           "P19,points / turnout,263009,DN MAIN,DN MAIN\n"          # leads to its own line
           "X1,Not a type,abc,NOWHERE,\n")
    p = _up(client, sid, "elements", bad, des).json()
    assert p["counts"] == {"add": 1, "update": 0, "error": 2} and not p["can_apply"]
    errs = {r["key"].split()[0]: r["errors"] for r in p["rows"]}
    assert any("different line" in e for e in errs["P19"])
    assert any("not a known value" in e for e in errs["X1"]) and any("not a number" in e for e in errs["X1"])
    assert any("not a line of this station" in e for e in errs["X1"])
    assert _up(client, sid, "elements", bad, des, apply=True).status_code == 422          # nothing saved
    assert client.get(f"/stations/{sid}/elements", headers=des).json() == []
    assert _up(client, sid, "elements", bad, chk).status_code == 403                      # checker cannot
    good = "element_ref,element_type,km,line,to_line\nS1,Main Home without Junction Route Indicator,261.789,DN MAIN,\nP19,Points / Turnout,263.009,DN MAIN,COMMON LOOP\n"
    r = _up(client, sid, "elements", good, des, apply=True).json()
    assert r["counts"]["add"] == 2
    els = {e["element_ref"]: e for e in client.get(f"/stations/{sid}/elements", headers=des).json()}
    assert els["S1"]["location_m"] == 261789 and els["P19"]["to_track_id"] is not None
    # again: exists -> error unless update_existing
    assert _up(client, sid, "elements", good, des).json()["counts"]["error"] == 2
    r = _up(client, sid, "elements", good.replace("261.789", "261.790"), des, apply=True, update=True).json()
    assert r["counts"]["update"] == 2
    assert {e["element_ref"]: e for e in client.get(f"/stations/{sid}/elements", headers=des).json()}["S1"]["location_m"] == 261790
    changes = client.get(f"/stations/{sid}/changes", headers=des)
    assert changes.status_code in (200, 403)


def test_tags_link_and_pair(client):
    sid, des, _ = _setup(client)
    _up(client, sid, "elements", "ref,type,location_m,line,to_line\nP19,Points / Turnout,263009,DN MAIN,COMMON LOOP\n",
        des, apply=True)
    csv_text = ("tag_ref,tag_type,location_m,line,direction,placed_for,paired_with,role\n"
                "R-836,T,262966,DN MAIN,Reverse,P19,R-844,main\n"
                "R-844,T,262966,DN MAIN,Reverse,P19,,\n"
                "R-850,T,263000,DN MAIN,Reverse,,,\n")
    p = _up(client, sid, "tags", csv_text, des).json()
    assert p["can_apply"], p
    assert any("without the points" in w for r in p["rows"] for w in r["warnings"])
    _up(client, sid, "tags", csv_text, des, apply=True)
    tags = {t["tag_ref"]: t for t in client.get(f"/stations/{sid}/tags", headers=des).json()}
    assert tags["R-836"]["tag_number"] == 836                                   # from the tag ID
    assert tags["R-836"]["linked_element_id"] is not None
    assert tags["R-836"]["pair_group_id"] == tags["R-844"]["pair_group_id"] == "PAIR-R-836/R-844"
    assert tags["R-844"]["is_duplicate"] and not tags["R-836"]["is_duplicate"]
    assert tags["R-836"]["legend_shape"] == "Rectangle"                          # co-located
    bad = "tag_ref,tag_type,location_m,placed_for,paired_with\nR-1,T,1,NOPE,R-999\n"
    errs = _up(client, sid, "tags", bad, des).json()["rows"][0]["errors"]
    assert any("not an element" in e for e in errs) and any("not a tag" in e for e in errs)


def test_tins_normalised_and_xlsx(client):
    sid, des, _ = _setup(client)
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["TIN No", "Section", "Line", "Colour", "Endpoint A", "Endpoint B", "Direction"])
    ws.append([218, "Block", "UP MAIN", "Orange", 266417, 263145, "Reverse"])
    ws.append([169, "Station", "DN MAIN", "Yellow", 261978, 261978, "Nominal"])
    buf = io.BytesIO()
    wb.save(buf)
    p = _up(client, sid, "tins", buf.getvalue(), des, name="tins.xlsx").json()
    rows = {r["key"].split(" (")[0]: r for r in p["rows"]}
    assert rows["TIN 218"]["action"] == "add" and rows["TIN 218"]["data"]["start_m"] == 263145
    assert any("high-to-low" in w for w in rows["TIN 218"]["warnings"])
    assert rows["TIN 169"]["action"] == "error" and any("equal" in e for e in rows["TIN 169"]["errors"])


QFTL_ELEMENTS = '''#,Name of the  Signal,Type of Signal,Location(m),Line,Dir,Remarks
,S1/S1A,"Main Home with Junction
 Route Indicator",261789,DN MAIN,Down,-
,S30 ID/29D,"Gate Inner Distant-Cum-
 Distant Signal",265370,UP MAIN,Up,-
,S30/29 ID,"Gate stop-cum-
Inner Distant  Signal",264362,UP MAIN,Up,-
,SB,Stop  Board /Buffer Stop,262977,UP MAIN,Up,-
,SB,Stop  Board /Buffer Stop,262982,UP MAIN,Up,-
,S5/SH8,Loopline Starter ,262907,DN MAIN,Down,-
'''
QFTL_TAGS = '''#,Tag Number,Type of Tag,Chainage(m),Line,Dir,Linked element,Pair group ID,Legend,Border tag
,R-775,S - Signal Foot Tag,259740,DN MAIN,Nominal (DN),S1/S1A,-,Triangle,Yes
,R-883,G - Lc Gate Tag,263574,DN MAIN,Nominal (DN),-,-,Triangle,No
,R-862,A - Adjustment / Junction Tag,261083 / 261144,UP MAIN,Reverse (UP),-,-,Triangle,No
'''
QFTL_TINS = '''#,TIN Number,TIN Placement,Line,Color,Start (m),End (m),No KAVACH territory
,169,Station,COMMON LOOP,Yellow,261978,262213,No
,169,Station,COMMON LOOP,Yellow,261978,262023,No
,218,Block,UP MAIN,Orange,270968,263145,No
'''


def test_qftl_sheet_format(client):
    """The column headings and cell values of the QFTL working sheets (ALER_*_test.csv)."""
    sid, des, _ = _setup(client)
    p = _up(client, sid, "elements", QFTL_ELEMENTS, des).json()
    assert p["ignored_columns"] == [] and p["can_apply"], p
    types = {r["key"]: r["data"]["element_type"] for r in p["rows"]}
    assert types["S1/S1A (DN MAIN)"] == "Main Home with Junction Route Indicator"
    assert types["S30 ID/29D (UP MAIN)"] == "Gate Inner Distant-cum-Distant Signal"
    assert types["S30/29 ID (UP MAIN)"] == "Gate-cum-Inner Distant Signal"
    assert types["SB (UP MAIN)"] == "Stop Board/Buffer Stop" and types["S5/SH8 (DN MAIN)"] == "Loopline Starter"
    assert p["counts"]["add"] == 6                                   # two SBs at different chainages
    _up(client, sid, "elements", QFTL_ELEMENTS, des, apply=True)
    p = _up(client, sid, "tags", QFTL_TAGS, des).json()
    assert p["can_apply"], p
    rows = {r["key"]: r for r in p["rows"]}
    assert rows["R-775"]["data"]["tag_type"] == "S" and rows["R-775"]["data"]["tag_number"] == 775
    assert rows["R-775"]["data"]["direction"] == "Nominal" and rows["R-775"]["data"]["is_border_tag"] is True
    assert rows["R-775"]["data"]["linked_element_id"] is not None
    assert rows["R-862"]["data"]["location_m"] == 261083 and rows["R-862"]["data"]["abs2_m"] == 261144
    p = _up(client, sid, "tins", QFTL_TINS, des).json()
    assert p["can_apply"] and p["counts"]["add"] == 3, p
    assert [r["data"]["section_type"] for r in p["rows"]] == ["Station", "Station", "Block"]


def test_update_keeps_values_left_blank(client):
    sid, des, _ = _setup(client)
    _up(client, sid, "elements", QFTL_ELEMENTS, des, apply=True)
    _up(client, sid, "tags", QFTL_TAGS, des, apply=True)
    blank_link = QFTL_TAGS.replace("S1/S1A,-,Triangle,Yes", "-,-,Triangle,Yes")
    _up(client, sid, "tags", blank_link, des, apply=True, update=True)
    t = {x["tag_ref"]: x for x in client.get(f"/stations/{sid}/tags", headers=des).json()}
    assert t["R-775"]["linked_element_id"] is not None


def test_qftl_templates(client):
    sid, des, _ = _setup(client)
    heads = {k: client.get(f"/stations/{sid}/registers/{k}/template", headers=des).text.splitlines()[0]
             for k in ("elements", "tags", "tins")}
    assert heads == {"elements": "#,Name of the  Signal,Type of Signal,Location(m),Line,Dir,Remarks",
                     "tags": "#,Tag Number,Type of Tag,Chainage(m),Line,Dir,Linked element,Pair group ID,Legend,Border tag",
                     "tins": "#,TIN Number,TIN Placement,Line,Color,Start (m),End (m),No KAVACH territory"}
