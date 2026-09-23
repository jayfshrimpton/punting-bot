"""Refresh horse histories from free daily Betfair WIN files; never refit weights."""
import argparse
import csv
import hashlib
import io
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen
from .core import Invalid, digest, now
from .model import archive_rows, build_features, load_races

LISTING='https://promo.betfair.com/betfairsp/prices/index.php'
FIELDS=['LOCAL_MEETING_DATE','TRACK','STATE_CODE','RACE_NO','WIN_MARKET_ID','RACING_TYPE','DISTANCE','SELECTION_ID','SELECTION_NAME','WIN_RESULT','WIN_BSP']
THOROUGHBRED=re.compile(r'^(?:Hcap|Mdn|CL[1-6]|[234]yo|Grp[123]|Listed|Qlty|Cup)$',re.I)

def download(url):
    if urlsplit(url).hostname!='promo.betfair.com':raise Invalid('Unexpected daily-data host')
    limit=80_000_000 if url==LISTING else 5_000_000
    with urlopen(url,timeout=40) as response:
        if urlsplit(response.url).hostname!='promo.betfair.com':raise Invalid('Unexpected daily-data redirect')
        raw=response.read(limit+1)
    if len(raw)>limit:raise Invalid('Daily-data response too large')
    return raw

def fetch(root, through):
    root.mkdir(parents=True,exist_ok=True)
    path=root/'manifest.json'
    manifest=json.loads(path.read_text()) if path.exists() else []
    known={e['name']:e for e in manifest}
    listing=download(LISTING).decode()
    links={Path(urlsplit(u).path).name:urljoin(LISTING,u) for u in re.findall(r'href=[\"\']([^\"\']+)',listing)}
    # Daily filenames refer to publication day, often the day after the races.
    for day in range(1,through.day+2):
        name=f'dwbfpricesauswin{day:02}092026.csv'
        if name not in links:raise Invalid('Daily file not listed: '+name)
        target=root/name
        if target.exists():
            if name not in known or hashlib.sha256(target.read_bytes()).hexdigest()!=known[name]['sha256']:
                raise Invalid('Unverified daily cache: '+name)
            continue
        time.sleep(3)
        raw=download(links[name])
        if raw.lstrip().startswith(b'<'):raise Invalid('Expected CSV, received HTML')
        target.write_bytes(raw)
        entry={'name':name,'source_url':links[name],'observed_at':now(),'sha256':hashlib.sha256(raw).hexdigest()}
        manifest.append(entry);known[name]=entry
        path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print('Downloaded '+name,flush=True)
    return manifest

def normalise(row, track_states, after, through):
    """Fail closed on unknown sport, jurisdiction, date or settlement."""
    event=re.fullmatch(r'R(\d+) (\d+)m (.+)',row['event_name'])
    if not event or not THOROUGHBRED.fullmatch(event[3]):return None,'non_thoroughbred_or_unknown_race_type'
    menu=re.fullmatch(r'(.+) \(AUS\) (\d{1,2})(?:st|nd|rd|th) (\w{3})',row['menu_hint'])
    if not menu:return None,'unknown_jurisdiction_or_date'
    # The displayed local meeting date, not publication filename or UTC off time.
    day=datetime.strptime(f'{menu[2]} {menu[3]} 2026','%d %b %Y').date()
    if not after<day<=through:return None,'outside_refresh_window'
    off=datetime.strptime(row['event_dt'],'%d-%m-%Y %H:%M').date()
    if abs((day-off).days)>1:raise Invalid('Daily file date disagrees with meeting label')
    states=track_states.get(menu[1].casefold(),set())
    if len(states)!=1:return None,'unmapped_or_ambiguous_track'
    if row['win_lose'] not in {'0','1'}:raise Invalid('Unsupported daily settlement')
    name=re.sub(r'^\d+\.\s*','',row['selection_name']).strip()
    if not name:raise Invalid('Empty horse name')
    return dict(zip(FIELDS,[day.isoformat(),menu[1],next(iter(states)),event[1],row['event_id'],'Thoroughbred',event[2],row['selection_id'],name,'WINNER' if row['win_lose']=='1' else 'LOSER',row['bsp']])),None

def refresh(through, data='data'):
    if not date(2026,9,1)<=through<=date(2026,9,29) or through>=date.today():
        raise Invalid('Use a completed September 2026 date, before today')
    data=Path(data);root=data/'history-september';root.mkdir(exist_ok=True)
    artifact_path=data/'model'/(data/'model/latest.txt').read_text().strip()
    artifact=json.loads(artifact_path.read_text())
    # A refresh always rebuilds from its frozen August parent, avoiding duplicate starts.
    base_name=artifact['model'].get('history_refresh_base')
    if base_name:
        artifact_path=data/'model'/base_name;artifact=json.loads(artifact_path.read_text())
    after=date.fromisoformat(artifact['model']['history_through'])
    if after!=date(2026,8,31):raise Invalid('Expected the frozen August history baseline')
    raw_manifest=fetch(root/'raw',through)
    tracks=defaultdict(set)
    for row in archive_rows(data/'history'):
        if row.get('RACING_TYPE','').lower()=='thoroughbred':tracks[row['TRACK'].casefold()].add(row['STATE_CODE'])
    converted=[];excluded=Counter();excluded_markets=defaultdict(set)
    for entry in raw_manifest:
        path=root/'raw'/entry['name']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise Invalid('Daily source hash mismatch')
        for row in csv.DictReader(path.open(encoding='utf-8-sig',newline='')):
            result,reason=normalise(row,tracks,after,through)
            if result:converted.append(result)
            else:excluded[reason]+=1;excluded_markets[reason].add(row['event_id'])
    # Drop entire markets with an unparseable row; never keep a partial race.
    rejected=set().union(*excluded_markets.values()) if excluded_markets else set()
    converted=[r for r in converted if r['WIN_MARKET_ID'] not in rejected]
    output=root/('normalised-'+digest(raw_manifest)[:12]+'-'+through.isoformat());output.mkdir(exist_ok=True)
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(converted)
    raw=stream.getvalue().encode();(output/'september.csv').write_bytes(raw)
    (output/'manifest.json').write_text(json.dumps([{'name':'september.csv','sha256':hashlib.sha256(raw).hexdigest(),'raw_sources':raw_manifest}],indent=2))
    races,invalid=load_races(output,through=through)
    if not races:raise Invalid('No validated September races')
    _,history=build_features(races,artifact['history'])
    last=max(r['date'] for r in races)
    changed=sum(history.get(k)!=v for k,v in artifact['history'].items())
    limitations=[f'Daily-file refresh through {last}; race-type and track mappings are conservative; excluded markets remain coverage gaps.']
    artifact['history']=history
    artifact['model'].update(history_through=last,created_at=now(),history_refresh_base=artifact_path.name,
        history_refresh_limitations=limitations,history_refresh={'requested_through':through.isoformat(),'races':len(races),'changed_existing_horses':changed,'row_exclusions':dict(excluded),'race_exclusions':invalid,'sources':raw_manifest,'normalised':str(output)})
    sid=digest(artifact);target=data/'model'/(sid+'.json')
    target.write_text(json.dumps(artifact),encoding='utf-8');(data/'model/latest.txt').write_text(target.name)
    print(json.dumps({'artifact':str(target),'history_through':last,'validated_races':len(races),'changed_existing_horses':changed,'row_exclusions':dict(excluded),'race_exclusions':invalid,'weights_refitted':False},indent=2))
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--through',required=True,type=date.fromisoformat)
    refresh(parser.parse_args().through)
