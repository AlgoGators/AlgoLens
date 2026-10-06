import { readFileSync } from 'node:fs';
import { describe,it,expect,vi } from 'vitest';
import { parseConfigurationInspection } from './configurationInspection';
const fixture = (name='equity_multi-v5') => JSON.parse(readFileSync(new URL(`../../../../algolens-api/tests/fixtures/configuration_inspection_v4_v5/${name}.json`,import.meta.url),'utf8'));
const response=(publication: ReturnType<typeof fixture>)=>({api_version:1,scope:{registry_id:publication.identity.registry_id,portfolio_id:publication.identity.portfolio_id},read_at:'2027-01-01T00:00:00Z',status:publication.status,reason:publication.reason,publication});
const parse=(publication:ReturnType<typeof fixture>)=>{const r=response(publication);return parseConfigurationInspection(JSON.stringify(r),r.scope.registry_id,r.scope.portfolio_id);};
describe('governed completed publication',()=>{
  vi.spyOn(Date,'now').mockReturnValue(Date.parse('2027-01-02T00:00:00Z'));
  it.each(['futures-v4','equity_house-v5','equity_now-v5','equity_empty_now-v5'])('accepts actual HTTP handoff %s',name=>{
    const r=fixture(`${name}.http`);
    expect(parseConfigurationInspection(JSON.stringify(r),r.scope.registry_id,r.scope.portfolio_id)).toEqual(r);
  });
  it.each(['equity_multi-v5','equity_now-v5','equity_empty_now-v5','equity_house-v5','futures-v4'])('accepts native %s',name=>expect(parse(fixture(name))).toEqual(response(fixture(name))));
  it.each(['hash','coverage','nested','owner','projection','attempt'])('refuses %s tampering',damage=>{
    const d=fixture();
    if(damage==='hash')d.configuration_selection.effective_sha256='a'.repeat(64);
    if(damage==='coverage')d.equity_multi_consumption.coverage.legacy_run_stages='observed';
    if(damage==='nested')d.equity_multi_consumption.portfolio_invocation.passes[0].risk_helper='fabricated';
    if(damage==='owner')d.source_to_storage_owners.ALPHA='OTHER';
    if(damage==='projection')d.supplied.fields.pop();
    if(damage==='attempt')d.identity.config_attempt_id='00000000-0000-0000-0000-000000000000';
    expect(()=>parse(d)).toThrow();
  });
});
