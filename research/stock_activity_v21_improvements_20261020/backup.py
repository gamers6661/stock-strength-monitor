from pathlib import Path
import shutil, json, hashlib
root=Path(r'D:\股票强势监测')
target=root/'research'/'stock_activity_v21_improvements_20261020'/'before'
target.mkdir(parents=True,exist_ok=True)
names=['stock_activity.py','stock_activity_engine.py','stock_activity_rules.py','stock_activity_ui.js','stock_activity_sampler.py','test_stock_activity.py','test_stock_activity_data.py','test_stock_activity_close.py','stock_activity_close.py','make_dashboard.py']
result={}
for name in names:
    src=root/name
    dst=target/name
    shutil.copy2(src,dst)
    result[name]={'size':dst.stat().st_size,'sha256':hashlib.sha256(dst.read_bytes()).hexdigest()}
(target/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('BACKUP_OK',len(result),str(target))
