"""Fixture + owned loopback accessory -> real setup route -> real conversion."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from snapstudio_api import ext_routes, routes_setups, service
from snapstudio_core.adapters import accessory_integration as ai, registry
from snapstudio_core.foundation.netguard import Response
from tests.integration.setup_helpers import project_cfg
from tests.integration.test_setup_to_prepare_journey import bundle, read_setup
from tests.test_project_materials import _project, _prepared

FIXTURES = Path(__file__).parent / 'fixtures' / 'adapters' / 'accessory'

def call(data):
    class H:
        def _send(self, code, body): self.answer = code, body
    h = H()
    ext_routes.dispatch(h, '/setups/evaluate', data)
    return h.answer

def eight():
    return {'live_slots': [{'ace': a, 'slot': h, 'material': 'PLA', 'color': '#123456'} for a in range(2) for h in range(4)],
            'head_ctx': {'mode': 'multi', 'head_nozzles': {str(h): 0.4 for h in range(4)}, 'head_ace': {str(h): h for h in range(4)},
                         'ace_heads': [], 'manual_heads': [], 'feeders': [], 'empty_slots': []}}

def spec(payload=None, **extra):
    return {'adapter_id': 'multiace', 'source_version': '1', 'mode': 'snapshot', 'payload': payload or eight(), **extra}

def lanes():
    return [f'lane:unit:multiace:ace{a}:{h}' for a in range(2) for h in range(4)]

def test_accessory_route_does_not_invent_slots_and_import_is_historical():
    code, body = call({'accessory': spec()})
    assert code == 200
    assert len(body['topology']['heads']) == 4 and len(body['topology']['units']) == 2
    assert body['topology']['slots'] == []
    assert all(o['historical'] for o in body['report']['entries'][0]['observations'])

def test_explicit_slot_map_reaches_real_prepare_and_preserves_original(tmp_path):
    code, body = call({'accessory': spec(slot_map=lanes())})
    assert code == 200
    t = body['topology']
    assert len(t['heads']) == 4 and len(t['slots']) == 8
    assert 'user-declared-slot-map' in t['evidence']
    caps={c['key']:c for c in body['report']['entries'][0]['capabilities']}
    assert caps['logical_slots']['reason'].startswith('You declared 8')
    assert 'not a device-reported' in caps['slot_mapping']['reason']
    src = _project(tmp_path, project_cfg(8), name='synthetic-eight.3mf')
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    result = service.convert(str(src), str(tmp_path/'output'), 'preserve', False, None, topology=t)
    cfg = _prepared(type('R', (), {'output_path': result['output_path']}))
    assert len(cfg['nozzle_temperature']) == 8
    assert len(cfg['z_hop']) == 4
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before

@pytest.mark.parametrize('delta', [{'adapter_id': []}, {'source_version':'unknown'}, {'slot_map':['missing']}, {'slot_map':[]}, {'mode':'probe'}])
def test_bad_specification_is_refused(delta):
    assert call({'accessory':spec(**delta)})[0] == 400

def test_live_get_uses_only_fixed_path_and_never_sends_octoprint_key(monkeypatch):
    seen=[]
    def request(method,url,**kwargs):
        seen.append((method,url,kwargs))
        b=json.dumps(eight()).encode()
        return Response(200, {'content-type':'application/json'},b,None,len(b))
    monkeypatch.setattr(routes_setups.netguard,'local_request',request)
    code, body=call({'api_key':'synthetic-key','accessory':spec(mode='live',host='127.0.0.1',port=8123,slot_map=lanes())})
    assert code == 200 and len(body['topology']['slots']) == 8
    assert len(seen)==1 and seen[0][0]=='GET' and seen[0][1].endswith('/multiace/api/preflight/livedata')
    assert 'headers' not in seen[0][2]
    assert not any(o['historical'] for o in body['report']['entries'][0]['observations'])

def test_live_accessory_runs_through_real_netguard_loopback():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args): pass
        def do_GET(self):
            seen.append(self.path)
            b=json.dumps(eight()).encode(); self.send_response(200)
            self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        code,body=call({'accessory':spec(mode='live',host='127.0.0.1',port=server.server_port,slot_map=lanes())})
        assert code==200 and len(body['topology']['slots'])==8
        assert seen==['/multiace/api/preflight/livedata']
    finally:
        server.shutdown();server.server_close();thread.join()

def test_host_head_evidence_can_complete_partial_accessory_but_never_contradict_it():
    from snapstudio_core.foundation.observations import to_iso
    from snapstudio_core.adapters.host import moonraker_stock
    host=moonraker_stock.INSTANCE.parse(bundle('four_heads_loaded'),received_at=to_iso(100),source_version='host_bundle/1')
    parsed=registry.get('multiace').parse(eight(),received_at=to_iso(100),source_version='1')
    parsed.topology.complete=False
    result=ai.compose(parsed,host,lanes(),historical=True)
    assert result.topology.complete and len(result.topology.heads)==4
    parsed.topology.heads[0].nozzle_mm=9.9
    with pytest.raises(ValueError): ai.compose(parsed,host,lanes())
    parsed.topology.units[0].lanes[0].reachable_heads=['head:99']
    with pytest.raises(ValueError): ai.compose(parsed,None,lanes())

@pytest.mark.parametrize('name,version,filename',[('afc','1','status_ok'),('bmcu','1','plan_ok'),('sidecar','beta-preview','gcode_processed')])
def test_all_four_parsers_are_reachable_from_setup_route(name,version,filename):
    files=list((FIXTURES/name/version).glob('*.json'))
    selected=next((p for p in files if p.stem==filename),None)
    if selected is None:
        selected=next(p for p in files if 'status' in p.stem and 'unknown' not in p.stem)
    payload=json.loads(selected.read_text(encoding='utf-8'))
    code,body=call({'accessory':{'adapter_id':name,'source_version':version,'mode':'snapshot','payload':payload}})
    assert code==200 and body['read']['adapter_id']==name
    assert body['topology'] is not None, (selected,body)

def test_auth_failure_has_no_topology_or_body_echo():
    code,body=call({'accessory':spec({'http_status':401,'body':{'private':'not-for-output'}})})
    assert code==200 and body['topology'] is None
    assert 'not-for-output' not in json.dumps(body)


def test_mapping_cannot_be_applied_to_unreadable_accessory():
    code,body=call({'accessory':spec({'http_status':401,'body':{}},slot_map=lanes())})
    assert code==400 and 'topology' in body['message']
