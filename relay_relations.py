"""Main business directions only; incidental common concept membership is insufficient."""
def industries(row):
    values=row.get('industry') or []
    if isinstance(values,str):values=[values]
    return {v for v in values+[row.get('primary_industry')] if v and v not in ('其他','综合','未知')}

def shared(a,b,rows):
    left=rows.get(a) or {};right=rows.get(b) or {}
    common=sorted(industries(left)&industries(right))
    result=[dict(id='main_industry:'+name,name=name,kind='main_industry',
        basis='双方同花顺F10主营行业共同归属：'+name,source='同花顺个股F10') for name in common]
    # Cross-industry concepts require dated business evidence on BOTH issuers.
    # The catalogue itself does not provide concept primacy, and ordering is not evidence.
    def primary(row):
        return {v['name']:v for v in row.get('mainline_concept_evidence',[])
            if isinstance(v,dict) and v.get('name') and v.get('source') and v.get('business_basis') and v.get('verified') is True}
    l=primary(left);r=primary(right)
    for name in sorted(set(l)&set(r)):
        result.append(dict(id='main_concept:'+name,name=name,kind='main_concept',
            basis='双方主营业务对应共同主线；'+l[name]['business_basis']+'；'+r[name]['business_basis'],
            sources=[l[name]['source'],r[name]['source']]))
    return result
