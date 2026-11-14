// An old evidence response must never replace a newer asset/view selection.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {style:{},querySelectorAll:()=>[],click:()=>{}});
  return elements.get(id);
};
const pending = new Map();
const requestCounts = new Map();
const context = vm.createContext({
  document:{getElementById:element,querySelectorAll:()=>[]}, URLSearchParams,
  setInterval:()=>1, clearInterval:()=>{},
  fetch: url => {requestCounts.set(url,(requestCounts.get(url)||0)+1);return new Promise(resolve=>pending.set(url,resolve));},
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../stratus/inspection/web/app.js'),'utf8'),context);
vm.runInContext('map = () => {};',context);
const older = vm.runInContext("choose('P01','overview')",context);
const newer = vm.runInContext("choose('P03','follow-up')",context);
function finish(asset,view,finding) {
  pending.get('/api/evidence?asset='+asset+'&view='+view)({ok:true,json:async()=>({
    asset_id:asset,view_id:view,status:'available',image_quality:'clear',finding,
    source_mode:'procedural_synthetic',assessment_mode:'authored_replay_annotation',
    evidence_ref:{evidence_id:asset+':'+view},annotation:{note:'Authored replay'},
  })});
}
(async()=>{
  finish('P03','follow-up','apparent_concern_review_required'); await newer;
  finish('P01','overview','no_apparent_concern'); await older;
  assert.equal(element('evidence-title').textContent,'P03 / follow-up');
  assert.equal(element('evidence-image').src,'/image?asset=P03&view=follow-up');
  assert.equal(element('finding').textContent,'Tentative concern');
  assert.match(element('provenance').textContent,/P03/);
  console.log('PASS: late evidence responses preserve the newest asset/view, finding and provenance');
  vm.runInContext("state={run:{aircraft_state:{revision:0},review_revision:0,plan_history:[],feedback:[]},current_plan:null};",context);
  const clickOne=vm.runInContext("workflowMutation('/api/execute',{plan_id:'one'})",context);
  const clickTwo=vm.runInContext("workflowMutation('/api/execute',{plan_id:'one'})",context);
  assert.equal(requestCounts.get('/api/execute'),1);
  pending.get('/api/execute')({ok:true,json:async()=>({event:{status:'executed'}})});
  await clickOne;await clickTwo;
  assert.match(element('workflow-message').textContent,/committed once/);
  console.log('PASS: repeated execution clicks send one request while a workflow mutation is pending');
  vm.runInContext("render=function(d){state=d};choose=async function(a,v){document.getElementById('chosen-capture').textContent=a+'/'+v};",context);
  const completed=vm.runInContext("workflowMutation('/api/execute',{plan_id:'follow-up'})",context);
  pending.get('/api/execute')({ok:true,json:async()=>({event:{status:'executed',evidence:{asset_id:'P05',view_id:'follow-up'}},state:{run:{aircraft_state:{revision:2},review_revision:1,plan_history:[],feedback:[]},current_plan:{plan_id:'next',proposal:{asset_id:'P02',view_id:'follow-up'},state_revision:2,review_revision:1,ground_context_id:'ground-test',execution_mode:'deterministic_rule_based'}}})});
  await completed;
  assert.equal(element('chosen-capture').textContent,'P05/follow-up');
  console.log('PASS: a committed capture opens its returned asset/view instead of the previously selected image');
  assert.equal(element('execute-plan').disabled,true);
  vm.runInContext("document.getElementById('execute-plan').onclick()",context);
  assert.equal(requestCounts.get('/api/execute'),2);
  console.log('PASS: a newly computed next plan needs explicit review before another capture can be sent');
})().catch(error=>{console.error(error);process.exitCode=1;});
