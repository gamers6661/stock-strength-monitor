import difflib,hashlib,json
from pathlib import Path
p=Path(__file__).parent
# The two-line board prefetch hook was copied immediately after its edit;
# reconstruct its pre-edit signature and fetch expression explicitly.
b=p/'baseline/board_trend.py'
old=b.read_text('utf8').replace("def attach(snapshot, calendar=None, fetch=True, path=None, quote_fetch=None, previous_snapshot=None,\n           quote_future=None):",
    "def attach(snapshot, calendar=None, fetch=True, path=None, quote_fetch=None, previous_snapshot=None):")
old=old.replace("quotes = quote_future.result() if quote_future is not None else board_quote.fetch(mapping[b['id']] for b in candidates)",
                "quotes = board_quote.fetch(mapping[b['id']] for b in candidates)")
out=[]
for name in ['ui_payload.py','serve.py','scoring.py','config.py','board_trend.py','scan_cache.py']:
    before=old if name=='board_trend.py' else (p/'baseline'/name).read_text('utf8')
    out.extend(difflib.unified_diff(before.splitlines(True),Path(name).read_text('utf8').splitlines(True),fromfile='before/'+name,tofile=name))
(p/'source_diff.txt').write_text(''.join(out),'utf8')
print('source diff saved')
