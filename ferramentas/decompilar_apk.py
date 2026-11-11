"""Decompila classes do app (com/star/v10 e com/pxn/v12) para arquivos .java."""
import os, sys, re, zipfile
from loguru import logger
logger.remove()
from androguard.core.dex import DEX
from androguard.core.analysis.analysis import Analysis
from androguard.decompiler.decompiler import DecompilerDAD

apk, out = sys.argv[1], sys.argv[2]
prefixes = tuple(sys.argv[3].split(","))
z = zipfile.ZipFile(apk)
dx = Analysis()
dexes = []
for dn in sorted(n for n in z.namelist() if re.fullmatch(r"classes\d*\.dex", n)):
    d = DEX(z.read(dn))
    dexes.append(d)
    dx.add(d)
dx.create_xref()
for d in dexes:
    d.set_decompiler(DecompilerDAD(d, dx))
    for c in d.get_classes():
        n = c.get_name()
        if not n.startswith(prefixes):
            continue
        path = os.path.join(out, n[1:-1].replace("$", "_") + ".java")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            src = c.get_source()
        except Exception as e:  # noqa
            src = f"// falha ao decompilar: {e}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
print("ok")
