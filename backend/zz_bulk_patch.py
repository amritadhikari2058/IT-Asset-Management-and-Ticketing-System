p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py"
src = open(p, encoding="utf-8").read()

old1 = """                else:
                    seen.add(tag)
                    if serial:
                        seen_serials.add(serial)
                    ok.append({"row": i, "asset_tag": tag})
            return Response({"preview": ok, "errors": errors})"""

new1 = """                else:
                    seen.add(tag)
                    if serial:
                        seen_serials.add(serial)
                    if str(r.get("status") or "available") == "assigned":
                        errors.append(
                            {"row": i,
                             "errors": "status 'assigned' cannot be imported; "
                                      "use the assign workflow"})
                    else:
                        ok.append({"row": i, "asset_tag": tag})
            return Response({"preview": ok, "errors": errors})"""

old2 = """                    obj = Asset(asset_tag=tag, name=r.get("name", tag),
                                category=cat,
                                serial_number=serial,
                                status=r.get("status", "available") or "available",
                                department=dept,"""

new2 = """                    if str(r.get("status") or "available") == "assigned":
                        failed.append(
                            {"row": i, "asset_tag": tag,
                             "errors": "status 'assigned' cannot be imported; "
                                       "use the assign workflow"})
                        continue
                    obj = Asset(asset_tag=tag, name=r.get("name", tag),
                                category=cat,
                                serial_number=serial,
                                status=r.get("status", "available") or "available",
                                department=dept,"""

old3 = """                    for k, v in changes.items():
                        setattr(obj, k, v)
                    obj.save()"""

new3 = """                    new_status = changes.get("status")
                    if (new_status is not None and new_status != obj.status
                            and new_status in ("assigned", "retired", "lost")):
                        failed.append(
                            {"asset_tag": r.get("asset_tag"),
                             "errors": f"Status '{new_status}' must be set "
                                       f"through its dedicated workflow "
                                       f"(assign, retire, or mark lost), not "
                                       f"generic editing."})
                        continue
                    for k, v in changes.items():
                        setattr(obj, k, v)
                    obj.save()"""

for o, n in ((old1, new1), (old2, new2), (old3, new3)):
    assert src.count(o) == 1, (o[:60], src.count(o))
    src = src.replace(o, n)

open(p, "w", encoding="utf-8").write(src)
print("bulk integrity patches ok")
