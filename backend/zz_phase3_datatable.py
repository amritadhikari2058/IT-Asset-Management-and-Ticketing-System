path = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\components.jsx"
src = open(path, encoding="utf-8").read()
lines = src.splitlines()

i_sel = next(i for i, l in enumerate(lines) if l.strip() == "const selectable = typeof onToggle === 'function';")
insert = [
    "  const selectable = typeof onToggle === 'function';",
    "  const pageKeys = rows.map((r) => keyOf(r));",
    "  const selSet = selected ?? new Set();",
    "  const allSel = pageKeys.length > 0 && pageKeys.every((k) => selSet.has(k));",
    "  const someSel = pageKeys.some((k) => selSet.has(k));",
    "  const handleToggleAll = () => {",
    "    const next = new Set(selSet);",
    "    const allOn = pageKeys.length > 0 && pageKeys.every((k) => next.has(k));",
    "    pageKeys.forEach((k) => { if (allOn) next.delete(k); else next.add(k); });",
    "    pageKeys.forEach((k) => {",
    "      const shouldHave = next.has(k);",
    "      if (shouldHave !== selSet.has(k)) onToggle(k);",
    "    });",
    "  };",
]
assert lines[i_sel].strip() == "const selectable = typeof onToggle === 'function';", lines[i_sel]
lines[i_sel:i_sel + 1] = insert

src = "\n".join(lines) + "\n"
old_th = "{selectable && <th className=\"th-select\"><span className=\"visually-hidden\">Select rows</span><span className=\"muted small\" aria-hidden=\"true\">?</span></th>}"
new_th = """{selectable && (
              <th className="th-select">
                <span className="visually-hidden">Select rows</span>
                <input
                  type="checkbox"
                  checked={allSel}
                  ref={(el) => { if (el) el.indeterminate = !allSel && someSel; }}
                  onChange={handleToggleAll}
                  aria-label="Select all rows on this page"
                />
              </th>
            )}"""
assert src.count(old_th) == 1, f"th anchor {src.count(old_th)}"
src = src.replace(old_th, new_th)
open(path, "w", encoding="utf-8").write(src)
print("datatable ok")
