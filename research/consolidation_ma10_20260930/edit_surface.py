from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=root/'trend_consolidation.py';s=p.read_text(encoding='utf-8')
start=s.index("        if setup.get('phase')=='completed':",s.index('def attach'))
end=s.index('        departed=departure_reason',start)
s=s[:start]+"        sampling=sampling_confirmation(row,setup,context,points.get(code,[]))\n"+s[end:]
p.write_text(s,encoding='utf-8')
