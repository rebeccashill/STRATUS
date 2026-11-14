(* STRATUS fixed numerical tool. All imported JSON is data; no ToExpression or arbitrary formulas. *)
ClearAll[stratusRequire, stratusNumber, computeInspectionOptions];
stratusRequire[condition_, message_] := If[!TrueQ[condition], Throw[<|"error" -> message|>, "stratus"]];
stratusNumber[x_] := NumberQ[x] && TrueQ[Abs[N[x]] <= 10^12];

computeInspectionOptions[input_Association] := Catch[Module[
  {keys, pointKeys, candidateKeys, candidates, position, launch, rate, options, pairs, out, ret, margin},
  keys = {"contract_version", "model_version", "mission_id", "mission_revision", "state_revision", "position", "launch", "distance_unit", "energy_unit", "battery_available", "capture_cost", "travel_energy_per_distance", "return_reserve", "remaining_actions", "candidates"};
  stratusRequire[Sort[Keys[input]] === Sort[keys], "Unexpected input fields"];
  stratusRequire[input["contract_version"] === "inspection-costs-v1" && input["model_version"] === "toy-euclidean-energy-v1", "Unsupported contract/model"];
  stratusRequire[input["distance_unit"] === "m" && input["energy_unit"] === "simulated_energy_unit", "Use normalized metre and simulated-energy inputs"];
  stratusRequire[And @@ (StringQ[input[#]] && 0 < StringLength[input[#]] <= 160 & /@ {"mission_id", "mission_revision"}), "Invalid mission identity"];
  stratusRequire[And @@ (IntegerQ[input[#]] && 0 <= input[#] <= 1000000 & /@ {"state_revision", "remaining_actions"}), "Invalid count/revision"];
  stratusRequire[And @@ (stratusNumber[input[#]] && input[#] >= 0 & /@ {"battery_available", "capture_cost", "travel_energy_per_distance", "return_reserve"}), "Invalid numeric costs/budget"];
  pointKeys = {"point_id", "x", "y"};
  Do[
    stratusRequire[AssociationQ[input[name]] && Sort[Keys[input[name]]] === Sort[pointKeys], "Invalid point fields"];
    stratusRequire[StringQ[input[name]["point_id"]] && 0 < StringLength[input[name]["point_id"]] <= 160, "Invalid point identity"];
    stratusRequire[stratusNumber[input[name]["x"]] && stratusNumber[input[name]["y"]], "Invalid point coordinates"],
    {name, {"position", "launch"}}];
  candidates = input["candidates"];
  stratusRequire[ListQ[candidates] && 1 <= Length[candidates] <= 128, "Invalid candidate batch"];
  candidateKeys = {"asset_id", "view_id", "x", "y"};
  Do[
    stratusRequire[AssociationQ[c] && Sort[Keys[c]] === Sort[candidateKeys], "Invalid candidate fields"];
    stratusRequire[And @@ (StringQ[c[#]] && 0 < StringLength[c[#]] <= 160 & /@ {"asset_id", "view_id"}), "Invalid candidate identity"];
    stratusRequire[stratusNumber[c["x"]] && stratusNumber[c["y"]], "Invalid candidate coordinate"],
    {c, candidates}];
  pairs = {#["asset_id"], #["view_id"]} & /@ candidates;
  stratusRequire[DuplicateFreeQ[pairs], "Duplicate asset/view"];
  position = N[{input["position"]["x"], input["position"]["y"]}];
  launch = N[{input["launch"]["x"], input["launch"]["y"]}];
  rate = N[input["travel_energy_per_distance"]];
  options = Map[Function[c,
    out = Norm[N[{c["x"], c["y"]}] - position] * rate;
    ret = Norm[N[{c["x"], c["y"]}] - launch] * rate;
    margin = N[input["battery_available"] - out - input["capture_cost"] - ret - input["return_reserve"]];
    <|"asset_id" -> c["asset_id"], "view_id" -> c["view_id"], "outbound" -> out,
      "capture" -> input["capture_cost"], "return_cost" -> ret, "reserve" -> input["return_reserve"],
      "margin" -> margin, "feasible" -> TrueQ[margin >= 0 && input["remaining_actions"] > 0]|>
  ], candidates];
  Join[KeyTake[input, {"contract_version", "model_version", "mission_id", "mission_revision", "state_revision", "distance_unit", "energy_unit"}],
       <|"options" -> options, "wolfram_version" -> $Version, "system_id" -> $SystemID|>]
], "stratus"];

Module[{args, input, result},
  args = Rest[$ScriptCommandLine];
  If[Length[args] =!= 2, Print["Expected input JSON and output JSON paths"]; Exit[2]];
  input = Quiet[Check[Import[args[[1]], "RawJSON"], $Failed]];
  result = If[AssociationQ[input], TimeConstrained[computeInspectionOptions[input], 5, <|"error" -> "Computation timeout"|>], <|"error" -> "Invalid input JSON"|>];
  If[!AssociationQ[result], result = <|"error" -> "Invalid computation result"|>];
  Export[args[[2]], result, "RawJSON"];
  If[KeyExistsQ[result, "error"], Exit[3]];
];
