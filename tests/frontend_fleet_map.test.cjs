const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

function desk(drones){
 const elements=new Map(),requests=[];
 const element=id=>{if(!elements.has(id))elements.set(id,{checked:false,value:'',hidden:false,querySelectorAll:()=>[]});return elements.get(id);};
 const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[]},URLSearchParams,setInterval:()=>1,fetch:(url)=>{requests.push(url);return new Promise(()=>{});}});
 for(const file of ['fleet_playback.js','fleet.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../stratus/inspection/web',file),'utf8'),context);
 const run=code=>vm.runInContext(code,context);
 const state={drones:Object.fromEntries(drones.map(d=>[d.drone_id,d])),assets:[],tasks:{},evidence:{},hazards:{hazards:[{state:'active',rectangle:{x_min:20,x_max:30,y_min:-5,y_max:5,buffer_m:1}}]}};
 run('fleet='+JSON.stringify(state));
 element('fleet-filter').value='all';element('fleet-sort').value='id';
 element('fleet-show-returned').checked=true;
 return {element,run,requests};
}
const drone=(id,status,x=24,y=0)=>({drone_id:id,status,position:{x,y},launch:{x,y:0},battery:100,reserve:15,actions_used:0,reason:'Recorded simulation state'});

test('a post-mission hazard keeps returned drones visible with distinct markers and optional hiding',()=>{
 const ui=desk([drone('D001','complete'),drone('D002','complete',28)]);
 const before=ui.run('JSON.stringify(fleet)'),requests=ui.requests.length;
 ui.run('drawMap()');
 assert.match(ui.element('fleet-map-summary').textContent,/All 2 drones returned to launch/);
 assert.match(ui.element('fleet-map-context').textContent,/2 returned drones have launch positions inside the reported area/);
 assert.equal(ui.element('fleet-map-context').hidden,false);
 assert.match(ui.element('fleet-map').innerHTML,/data-drone="D001"/);
 ui.element('fleet-show-returned').checked=false;
 ui.element('fleet-show-returned').onchange();
 assert.doesNotMatch(ui.element('fleet-map').innerHTML,/data-drone=/);
 ui.element('fleet-show-returned').checked=true;
 ui.element('fleet-show-returned').onchange();
 assert.match(ui.element('fleet-map').innerHTML,/data-drone="D001"[^>]*aria-label="Select D001, Returned to launch"/);
 assert.match(ui.element('fleet-map').innerHTML,/cx="337" cy="335"/);
 assert.match(ui.element('fleet-map').innerHTML,/fill="#09090b"/);
 assert.equal(ui.run('JSON.stringify(fleet)'),before);
 assert.equal(ui.requests.length,requests);
});

test('hiding returned markers keeps held and in-mission drones inside a hazard visible',()=>{
 const ui=desk([drone('D001','complete'),drone('D002','held',25,2),drone('D003','traveling',26,3)]);
 ui.element('fleet-show-returned').checked=false;
 ui.run('drawMap()');
 const map=ui.element('fleet-map').innerHTML;
 assert.doesNotMatch(map,/data-drone="D001"/);
 assert.match(map,/data-drone="D002"[^>]*aria-label="Select D002, Held for operator review"/);
 assert.match(map,/data-drone="D003"[^>]*aria-label="Select D003, Traveling"/);
 assert.match(ui.element('fleet-map-summary').textContent,/1 in mission \/ 1 held for review \/ 1 returned/);
 ui.run("chooseDrone('D001')");
 assert.equal(ui.element('fleet-show-returned').checked,true);
 assert.match(ui.element('fleet-selected-state').textContent,/Returned to launch \/ recorded position/);
 assert.match(ui.element('fleet-map').innerHTML,/data-drone="D001"/);
 assert.match(ui.element('fleet-rows').innerHTML,/Returned to launch/);
});

test('a completed record away from launch is kept visible and never labeled returned',()=>{
 const d=drone('D001','complete');d.position.y=2;
 const ui=desk([d]);ui.run('drawMap()');
 assert.match(ui.element('fleet-map').innerHTML,/data-drone="D001"/);
 assert.equal(ui.element('fleet-returned-count').textContent,0);
 assert.equal(ui.element('fleet-map-context').hidden,true);
});
