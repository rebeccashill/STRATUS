'use strict';
// One bounded request in flight. A stopped generation cannot schedule another tick.
class FleetPlayback {
 constructor(advance,ready,schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id)){this.advance=advance;this.ready=ready;this.schedule=(fn,ms)=>schedule(fn,ms);this.cancel=id=>cancel(id);this.generation=0;this.timer=null;}
 stop(){this.generation++;this.cancel(this.timer);this.timer=null;}
 async start(){this.stop();const generation=this.generation;await this.tick(generation);}
 async tick(generation){
  if(generation!==this.generation||!this.ready())return;
  const success=await this.advance();
  if(!success){if(generation===this.generation)this.stop();return;}
  if(generation===this.generation&&this.ready())this.timer=this.schedule(()=>this.tick(generation),200);
 }
}
function fleetCheckpointSelection(names,previous,saved=null){return names.includes(saved)?saved:names.includes(previous)?previous:names[0]||'';}
function fleetExplanationText(result,m){
 const verified=m.drone_participation+'/'+m.fleet_size+' drones have captured evidence; '+m.unique_usable_assets+'/200 assets have a usable replay view and '+m.unresolved_assets+' remain unresolved. Modeled energy used: '+m.total_energy_EU.toFixed(2)+' EU. Battery remaining: '+m.total_battery_EU.toFixed(2)+' EU. Exclusive ownership, capture caps and return reserves govern execution; the heuristic is not globally optimal.';
 if(result?.mode==='live_ai_explanation'&&!/\d/.test(result.text))return 'AI explanation: '+result.text;
 return (result?.mode==='live_ai_explanation'?'AI numeric claims set aside. Verified summary: ':result?.mode==='local_rule_fallback'?'AI unavailable; verified local summary: ':'Verified local summary: ')+verified;
}
if(typeof module!=='undefined')module.exports={FleetPlayback,fleetCheckpointSelection,fleetExplanationText};
