"""Validate the recorded full comparison without repeating costly reconstruction."""
import json
from pathlib import Path

here=Path(__file__).resolve().parent
source=here/'frozen_results.json'
result=json.loads(source.read_text(encoding='utf-8'))
raw=result['differences']
assert result['difference_count']==len(raw), 'Truncated differences require another full comparison'
assert result['stocks']==3120 and result['boards']==539
assert result['same_warm_cold']
assert all(p.startswith('/history_reference/generated') for p in raw), raw
result['execution_differences']=raw
result['judgment_difference_count']=0
result['validation']='Recorded complete comparison; only first-run reference generation metadata differed'
(here/'frozen_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result[k] for k in ('stocks','boards','judgment_difference_count','execution_differences','same_warm_cold')},ensure_ascii=False))
