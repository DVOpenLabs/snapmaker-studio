"""Real Lumina HTTP mock -> saved valid 3MF -> explicit local open -> conversion."""
import hashlib
import os
from pathlib import Path
import pytest
from snapstudio_api import ext_routes, routes_engines, service
from snapstudio_core.engines.generated_files import verified_model
from tests.mocks.lumina_server import LuminaHttpMock
from tests.fixtures.creative.zip_factory import make_kromacut
from tests.integration.setup_helpers import project_cfg
from snapstudio_core.foundation.netguard import clear_write_origins

def call(path,data):
    class H:
        def _send(self,c,b): self.answer=c,b
    h=H();ext_routes.dispatch(h,path,data);return h.answer

def test_real_mock_generation_open_and_prepare(tmp_path,monkeypatch):
    monkeypatch.setenv('SNAPSTUDIO_DATA_DIR',str(tmp_path/'data'))
    src=tmp_path/'synthetic-model.3mf'; src.write_bytes(make_kromacut())
    model=src.read_bytes()
    image_dir=tmp_path/'images';image_dir.mkdir();image=image_dir/'synthetic.png';image.write_bytes(b'synthetic-image')
    with LuminaHttpMock(preview_id='preview',generate_id='model',glb_id=None,artifacts={'preview':('image/png',b'synthetic-png'), 'model':('model/3mf',model)}) as mock:
        code,result=call('/engines/lumina/generate',{'service_url':mock.url,'image_path':str(image),'lut_name':'Synthetic','format':'3mf','width_mm':75.0})
        assert code==200 and result['generated']
        assert b'name="target_width_mm"' in mock.uploads[0]["bytes"]
        assert b'\r\n\r\n75.0\r\n' in mock.uploads[0]["bytes"]
        assert mock.generations == [{'session_id':'session1','params':{'source_kind':'legacy_single','lut_name':'Synthetic','target_width_mm':75.0}}]
        assert ('POST','/api/convert/generate') in mock.requests
        assert ('GET','/api/files/preview') not in mock.requests
        before=list(mock.requests)
        code,opened=call('/engines/lumina/open_generated',result)
        assert code==200
        target=Path(opened['output']['local_path'])
        assert target.read_bytes()==model and hashlib.sha256(model).hexdigest()==opened['sha256']
        converted=service.convert(str(target),str(tmp_path/'prepared'),'preserve',False,None)
        assert converted['validated_ok'] and target.read_bytes()==model
        assert mock.requests==before # handoff and Prepare do not call Lumina again
    clear_write_origins()
    assert image.read_bytes()==b'synthetic-image'

@pytest.mark.parametrize('name',['../private.3mf','x.3mf','lumina-'+'a'*12+'.png','lumina-'+'a'*12+'.3mf:stream'])
def test_handoff_refuses_arbitrary_names(tmp_path,name):
    with pytest.raises(ValueError): verified_model(str(tmp_path),name,'a'*64)

def test_changed_missing_and_invalid_containers_are_refused_without_path_echo(tmp_path,monkeypatch):
    monkeypatch.setenv('SNAPSTUDIO_DATA_DIR',str(tmp_path))
    folder=tmp_path/'lumina-output';folder.mkdir()
    data=b'not-a-3mf';sha=hashlib.sha256(data).hexdigest();name='lumina-'+sha[:12]+'.3mf'
    request={'file_name':name,'sha256':sha}
    for state in ('missing','invalid','changed'):
        if state=='invalid': (folder/name).write_bytes(data)
        if state=='changed': (folder/name).write_bytes(b'changed')
        code,body=call('/engines/lumina/open_generated',request)
        assert code==422 and str(tmp_path) not in str(body)


@pytest.mark.parametrize('encoding',['utf-16le','utf-16be'])
def test_generated_utf16_entity_model_is_not_opened(tmp_path,encoding):
    import io, zipfile
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('3D/3dmodel.model', ('<!DOCTYPE model [<!ENTITY x "expanded">]><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">&x;</model>').encode(encoding))
    data=b.getvalue();sha=hashlib.sha256(data).hexdigest();name='lumina-'+sha[:12]+'.3mf'
    (tmp_path/name).write_bytes(data)
    with pytest.raises(ValueError): verified_model(str(tmp_path),name,sha)


def test_3mf_requires_advertised_generation_route_not_just_a_preview(tmp_path,monkeypatch):
    monkeypatch.setenv('SNAPSTUDIO_DATA_DIR',str(tmp_path/'data'))
    image=tmp_path/'synthetic.png';image.write_bytes(b'synthetic-image')
    with LuminaHttpMock(support_generate=False) as mock:
        code,body=call('/engines/lumina/generate',{'service_url':mock.url,'image_path':str(image),'lut_name':'Synthetic','format':'3mf'})
        assert code==422 and body['code']=='route_unavailable'
        assert ('POST','/api/convert/generate') not in mock.requests
        assert not list((tmp_path/'data'/'lumina-output').glob('*'))
    clear_write_origins()

@pytest.mark.parametrize('width',[False,0,999,float('nan'),'wide'])
def test_bad_width_is_refused_before_sending_image(tmp_path,width):
    code,body=call('/engines/lumina/generate',{'service_url':'http://127.0.0.1:8123','image_path':str(tmp_path/'missing.png'),'lut_name':'Synthetic','format':'3mf','width_mm':width})
    assert code==400 and 'width' in body['message'].lower()


def test_network_budget_is_shared_across_discovery_and_health(monkeypatch):
    from snapstudio_core.engines import lumina
    from snapstudio_core.foundation.netguard import NetguardRefused, Response
    clock=[0.0]; seen=[]
    from types import SimpleNamespace
    monkeypatch.setattr(lumina,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    def request(method,url,**kwargs):
        import json
        seen.append(kwargs['timeout'])
        payload={'info':{'version':'2.0'},'paths':{'/api/health':{}}}
        data=json.dumps(payload).encode();clock[0]=11.0
        return Response(200,{},data,None,len(data))
    client=lumina.LuminaClient('http://127.0.0.1:8123',request=request,timeout=120,budget_s=10)
    client.discover()
    with pytest.raises(NetguardRefused):client.health_check()
    client.close()
    assert seen==[10.0]
