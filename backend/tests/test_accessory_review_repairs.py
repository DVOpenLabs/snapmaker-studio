"""Returned accessory attribution and unavailable-read regressions; fixtures/loopback only."""
import json
import socket
import pytest
from snapstudio_api import routes_setups
from snapstudio_core.adapters import accessory_integration as ai, registry
from snapstudio_core.foundation import netguard
from snapstudio_core.foundation.observations import to_iso
from tests.test_accessory_workflow import call, spec, eight, FIXTURES

@pytest.mark.parametrize('name,version,filename', [('bmcu','1','plan_ok'),('sidecar','beta-preview','gcode_processed')])
def test_reported_mapping_cannot_be_replaced_by_user_map(name,version,filename):
    payload=json.loads((FIXTURES/name/version/(filename+'.json')).read_text(encoding='utf8'))
    adapter=registry.get(name)
    parsed=adapter.parse(payload,received_at=to_iso(100),source_version=version)
    assert parsed.topology.slots or parsed.topology.bindings
    original=parsed.topology.to_dict()
    target=parsed.topology.units[0].lanes[0].id
    with pytest.raises(ValueError,match='already reports'):
        ai.compose(parsed,None,[target])
    assert parsed.topology.to_dict()==original
    body={'adapter_id':name,'source_version':version,'mode':'snapshot','payload':payload}
    code,response=call({'accessory':body});assert code==200
    assert response['topology']['slots']==original['slots']
    code,response=call({'accessory':{**body,'slot_map':[target]}})
    assert code==400 and 'cannot be overridden' in response['message']

def test_head_evidence_is_not_relabelled_as_user_declaration(monkeypatch):
    # Synthetic complete two-head parser seam: current multiACE queries four
    # heads, so a two-entry nozzle reply alone correctly remains incomplete.
    original_get=registry.get
    original_parse=original_get('multiace').parse
    def complete_two_heads(*args,**kwargs):
        parsed=original_parse(*args,**kwargs)
        parsed.topology.complete=True
        return parsed
    from types import SimpleNamespace
    monkeypatch.setattr(registry,'get',lambda name: SimpleNamespace(parse=complete_two_heads) if name=='multiace' else original_get(name))
    payload=eight()
    payload['head_ctx']['head_nozzles']={'0':0.4,'1':0.4}
    payload['head_ctx']['head_ace']={'0':0,'1':1}
    payload['live_slots']=[{'ace':a,'slot':h,'material':'PLA','color':'#123456'} for a in range(4) for h in range(2)]
    mapping=[f'lane:unit:multiace:ace{a}:{h}' for a in range(4) for h in range(2)]
    code,body=call({'accessory':spec(payload,slot_map=mapping)})
    assert code==200 and len(body['topology']['heads'])==2
    reasons=body['report']['legacy_limitation']['reasons']
    assert any(reason.startswith('This setup reports 2 physical heads') for reason in reasons)
    assert any(reason.startswith('You declared 8 logical slots') for reason in reasons)
    assert not any(reason.startswith('You declared 2 physical') for reason in reasons)

@pytest.mark.parametrize('reason',['network','deadline','unavailable','redirect'])
def test_live_transport_failure_is_unavailable_not_off_network(monkeypatch,reason):
    def fail(*args,**kwargs):raise netguard.NetguardRefused(reason)
    monkeypatch.setattr(routes_setups.netguard,'local_request',fail)
    code,body=call({'accessory':spec(mode='live',host='127.0.0.1',port=8123)})
    assert code==200 and body['read']['status']=='unavailable' and body['topology'] is None
    assert body['read']['reason']==str(netguard.NetguardRefused(reason))
    assert body['report']['entries'][0]['status']=='unavailable'
    assert 'only talks to devices' not in json.dumps(body)

def test_closed_owned_loopback_port_is_reported_unavailable():
    with socket.socket() as closed_service:
        closed_service.bind(('127.0.0.1',0))  # Bound, deliberately not listening; nobody else can take the port.
        code,body=call({'accessory':spec(mode='live',host='127.0.0.1',port=closed_service.getsockname()[1])})
    assert code==200 and body['read']['status']=='unavailable'
    assert body['topology'] is None
    assert body['read']['reason'] in {str(netguard.NetguardRefused('network')),str(netguard.NetguardRefused('deadline'))}

def test_public_address_stays_refused():
    assert call({'accessory':spec(mode='live',host='8.8.8.8',port=8123)})[0]==400

def test_busy_origin_lookup_is_unavailable_without_claiming_a_get(monkeypatch):
    def busy(*args,**kwargs):raise netguard.NetguardRefused('unavailable')
    monkeypatch.setattr(routes_setups.netguard,'require_local_url',busy)
    code,body=call({'accessory':spec(mode='live',host='127.0.0.1',port=8123)})
    assert code==200 and body['read']['status']=='unavailable'
    assert body['read']['reason']==str(netguard.NetguardRefused('unavailable'))
    assert body['read']['requests']==[]


def test_invalid_request_fields_fail_before_any_network_read(monkeypatch):
    calls=[]
    monkeypatch.setattr(routes_setups.netguard,"local_request",lambda *a,**k:calls.append(a))
    for extra in ({"requirements":"not-a-list"},{"requirements":[{"material":"x"*65}]},{"api_key":"bad key\n","host":"127.0.0.1"}):
        code,body=call({"accessory":spec(mode="live",host="127.0.0.1",port=8123),**extra})
        assert code==400,(extra,code,body)
        if "api_key" in extra: assert "api_key" in json.dumps(body),body
    assert calls==[]
