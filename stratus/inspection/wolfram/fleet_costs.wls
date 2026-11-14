(* Fixed data-only fleet batch. Same toy Euclidean model; no arbitrary expressions. *)
ClearAll[need,number,compute];
need[x_,m_]:=If[!TrueQ[x],Throw[<|"error"->m|>,"fleet"]];
number[x_]:=NumberQ[x]&&TrueQ[Abs[N[x]]<=10^12];
compute[d_Association]:=Catch[Module[{keys,rows,options,out,ret,margin},
 keys={"contract_version","model_version","scenario_id","fleet_revision","hazard_revision","pairs"};
 need[Sort[Keys[d]]===Sort[keys],"Unexpected envelope"];
 need[d["contract_version"]==="stratus-fleet-costs-v1"&&d["model_version"]==="toy-euclidean-energy-v1","Unsupported model"];
 need[StringQ[d["scenario_id"]]&&And@@(IntegerQ[d[#]]&&d[#]>=0&/@{"fleet_revision","hazard_revision"}),"Invalid revision"];
 rows=d["pairs"];need[ListQ[rows]&&1<=Length[rows]<=500,"Invalid bounded batch"];
 need[DuplicateFreeQ[{#["drone_id"],#["task_id"]}&/@rows],"Duplicate pair"];
 options=Map[Function[r,
  need[AssociationQ[r]&&Sort[Keys[r]]===Sort[{"drone_id","task_id","asset_id","view_id","drone_revision","task_revision","position","target","launch","battery","capture","rate","reserve","remaining_actions","distance_unit","energy_unit"}],"Unexpected pair fields"];
  need[And@@(StringQ[r[#]]&&0<StringLength[r[#]]<=160&/@{"drone_id","task_id","asset_id","view_id"}),"Invalid IDs"];
  need[r["distance_unit"]==="m"&&r["energy_unit"]==="simulated_energy_unit","Invalid units"];
  need[And@@(IntegerQ[r[#]]&&r[#]>=0&/@{"drone_revision","task_revision","remaining_actions"}),"Invalid counts"];
  need[And@@(number[r[#]]&&r[#]>=0&/@{"battery","capture","rate","reserve"}),"Invalid budgets"];
  Do[need[AssociationQ[r[k]]&&Sort[Keys[r[k]]]===Sort[{"x","y"}]&&And@@(number[r[k][#]]&/@{"x","y"}),"Invalid points"],{k,{"position","target","launch"}}];
  out=Norm[N[{r["target"]["x"]-r["position"]["x"],r["target"]["y"]-r["position"]["y"]}]]*r["rate"];
  ret=Norm[N[{r["target"]["x"]-r["launch"]["x"],r["target"]["y"]-r["launch"]["y"]}]]*r["rate"];
  margin=N[r["battery"]-out-r["capture"]-ret-r["reserve"]];
  Join[KeyTake[r,{"drone_id","task_id","asset_id","view_id","drone_revision","task_revision"}],<|"outbound"->out,"capture"->r["capture"],"return_cost"->ret,"reserve"->r["reserve"],"margin"->margin,"feasible"->TrueQ[margin>=0&&r["remaining_actions"]>0]|>]
 ],rows];
 Join[KeyDrop[d,{"pairs"}],<|"options"->options,"wolfram_version"->$Version,"system_id"->$SystemID|>]
],"fleet"];
Module[{args=Rest[$ScriptCommandLine],data,result},
 If[Length[args]=!=2,Exit[2]];data=Quiet[Check[Import[args[[1]],"RawJSON"],$Failed]];
 result=If[AssociationQ[data],TimeConstrained[compute[data],8,<|"error"->"Timeout"|>],<|"error"->"Invalid JSON"|>];
 If[!AssociationQ[result],result=<|"error"->"Invalid output"|>];Export[args[[2]],result,"RawJSON"];If[KeyExistsQ[result,"error"],Exit[3]];
];
