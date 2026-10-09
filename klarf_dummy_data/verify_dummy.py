"""Validate synthetic fixtures; does not validate any production classifier."""
from pathlib import Path
import csv, hashlib, json, math, platform, sys
from importlib.metadata import version
import klarfio

root=Path(__file__).resolve().parent
manifest=json.loads((root/'manifest.json').read_text())
profile=json.loads((root/'synthetic_profile.json').read_text())
report={'python':sys.version,'platform':platform.platform(),
        'klarfio_version':version('klarfio'),'validation_scope':'synthetic parsing, coordinates, bin and clock counts only',
        'production_adapter':'NOT_RUN','classifier':'NOT_RUN','application_e2e':'NOT_RUN','cases':[]}
try:
    import klarfrs
    report['klarfrs_version']=version('klarfrs')
except ImportError:
    klarfrs=None

for case in manifest['cases']:
    name=case['name'];path=root/'klarf'/(name+'.klarf')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==case['file_sha256'],name
    obj=klarfio.klarf(filename=str(path))
    wafer=obj.data['FileRecord_1.8']['LotRecord_DUMMY_LOT']['WaferRecord_'+name]
    table=wafer['DefectList']
    columns=[c['Column'] for c in table['Columns']]
    data=[dict(zip(columns,row)) for row in table['Data']]
    oracle=list(csv.DictReader((root/'expected'/(name+'.csv')).open()))
    assert len(data)==case['count']==len(oracle),name
    assert wafer['OrientationMarkLocation']==[case['notch']],name
    bins={};clock={str(h):0 for h in range(1,13)};center=0
    zones={k:[] for k in ['E1','E2','inner_100mm','boundary_100mm']}
    a=math.radians(profile['rotation_to_notch_down_clockwise_deg'][case['notch']])
    for row,expected in zip(data,oracle):
        assert row['DEFECTID']==int(expected['defect_id']),name
        assert 0<=row['XREL']<10000 and 0<=row['YREL']<10000,name
        rawx=(row['XINDEX']*10000+row['XREL']-150000)/1000
        rawy=(row['YINDEX']*10000+row['YREL']-150000)/1000
        x=rawx*math.cos(a)+rawy*math.sin(a)
        y=-rawx*math.sin(a)+rawy*math.cos(a)
        assert abs(x-float(expected['x_mm']))<1e-7,name
        assert abs(y-float(expected['y_mm']))<1e-7,name
        b=str(row['CLASSNUMBER'])
        assert b==expected['classification_bin'],name
        assert row['FINEBINNUMBER']==row['CLASSNUMBER']==row['ROUGHBINNUMBER'],name
        bins[b]=bins.get(b,0)+1
        r=math.hypot(x,y)
        hour='center' if r<1 else str((int(((math.degrees(math.atan2(x,y))+15)%360)//30) or 12))
        assert hour==expected['clock_hour'],name
        if hour=='center':center+=1
        else:clock[hour]+=1
        if 0<=150-r<2:zones['E1'].append(row['DEFECTID'])
        if 2<=150-r<5:zones['E2'].append(row['DEFECTID'])
        if r<100:zones['inner_100mm'].append(row['DEFECTID'])
        if 99<=r<=101:zones['boundary_100mm'].append(row['DEFECTID'])
    assert bins==case['bin_counts'] and clock==case['clock_counts'],name
    assert center==case['center_count'] and zones==case['zone_support_ids'],name
    assert sum(bins.values())==sum(clock.values())+center==len(data),name
    if name.startswith('F01'):
        assert bins=={'1':3,'2':3,'3':2} and center==1
        assert clock['12']==1 and clock['3']==4 and clock['6']==1 and clock['9']==1
        assert zones=={'E1':[6],'E2':[7],'inner_100mm':[1,2,3,4,5],'boundary_100mm':[8]}
    result={'name':name,'count':len(data),'klarfio_coordinates_bins_clock_zones':'PASS'}
    if klarfrs:
        try:
            parsed=klarfrs.parse_defects(str(path));header=klarfrs.parse(str(path))
            compatible=(len(parsed)==len(data) and header.file_version.strip() in ('1.8','1 8'))
            if compatible:
                compatible=all(p.defect_id==r['DEFECTID'] and p.class_number==r['CLASSNUMBER']
                    and abs(p.xrel-r['XREL'])<1e-7 and abs(p.yrel-r['YREL'])<1e-7
                    for p,r in zip(parsed,data))
            result['klarfrs_compatibility']='PASS' if compatible else 'FAIL'
            result['klarfrs_count']=len(parsed)
            result['klarfrs_file_version']=header.file_version
        except Exception as exc:
            result['klarfrs_compatibility']='FAIL';result['klarfrs_error']=str(exc)
    else:result['klarfrs_compatibility']='NOT_RUN'
    report['cases'].append(result)

(root/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS: synthetic syntax/coordinates/bin/clock/zone checks:',len(report['cases']))
print('klarfrs compatibility failures:',sum(c['klarfrs_compatibility']=='FAIL' for c in report['cases']))
print('Production adapter, classifier and app E2E: NOT_RUN')
