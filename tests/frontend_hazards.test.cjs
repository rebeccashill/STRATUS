const assert=require('node:assert/strict');
const test=require('node:test');
const api=require('../stratus/inspection/web/hazards.js');
function fixture(n){return{mode:'fixture_host_not_part12_fleet_integration',drones:Object.fromEntries(Array.from({length:n},(_,i)=>['D'+String(i+1).padStart(3,'0'),{actions_used:i%2}])),current_paths:[{drone_id:'D001',hazard_revision:2}],proposals:{},hazards:{registry:{revision:2,hazards:{a:{state:'review_required'},b:{state:'cleared'}}},latest_impact:{assessed_count:n,affected_count:2}}};}
test('all 50 fixture records contribute to displayed accounting',()=>{assert.deepEqual(api.summary(fixture(50)),{revision:2,assessed:50,affected:2,captures:25,restricted:1,fixture:true});});
test('missing proposal remains explicit rather than displaying a fresh authorization',()=>{assert.equal(api.selectedAssessment(fixture(2),'D001').proposal,null);});
test('empty registry does not invent an assessment',()=>{const s=fixture(2);s.hazards.latest_impact=null;s.hazards.registry={revision:0,hazards:{}};const r=api.summary(s);assert.equal(r.assessed,0);assert.equal(r.affected,0);assert.equal(r.restricted,0);});
