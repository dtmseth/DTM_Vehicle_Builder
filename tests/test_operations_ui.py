"""Focused Operations interaction checks without launching a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def run_ui(script, relative_source="operations.js"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for isolated UI function checks")
    source = Path(__file__).parents[1] / "src/dtm_buildsheet/ui/js" / relative_source
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_status_refresh_follows_project_and_preserves_disclosures_and_viewport():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,value:'',classList:{toggle(){}}});return nodes.get(id);};
const window={scrollY:500,scrollX:0,scrollTo({top}){this.scrollY=top;}};
function node(key,y,extra={}){return {dataset:{operationsViewKey:key,...extra},open:true,
 getBoundingClientRect(){return {top:y-window.scrollY,bottom:y-window.scrollY+400};},closest(){return this;}};}
let groups=[node('project:p',600,{operationsProjectId:'p'})];
let overrides=[{dataset:{operationsOverrideId:'v1'},open:true},{dataset:{operationsOverrideId:'v2'},open:false}];
let anchor=node('["vehicle","v1","availability"]',850),rowNodes=[...groups,anchor];
const rows=$('operations-rows');
rows.querySelectorAll=selector=>selector==='.operations-project-group'?groups:selector==='.operations-vehicle-quick'?overrides:rowNodes;
let rendered=[];
Object.defineProperty(rows,'innerHTML',{set(value){
 rendered=value.trim()?value.trim().split('\n').map(JSON.parse):[];
 groups=rendered.map(p=>({...node('project:'+p.id,900,{operationsProjectId:p.id}),open:p.open}));
 overrides=rendered.flatMap(p=>p.ids.map(id=>({dataset:{operationsOverrideId:id},open:false})));
 rowNodes=[...groups,node('["vehicle","v1","availability"]',1150)];
}});
const document={addEventListener(){},querySelectorAll(selector){
 if(selector==='.operations-project-group[open]')return groups.filter(p=>p.open);
 if(selector==='.operations-vehicle-quick[open]')return overrides.filter(p=>p.open);
 return [];
}};
let incoming,failed=false,hiddenDuringLoad=false;const notices=[];
const context=vm.createContext({document,window,$,console,Set,Map,toast:(...args)=>notices.push(args),
 api:async()=>{hiddenDuringLoad=$('operations-content').hidden;if(failed)return {ok:false,error:'Offline'};return incoming;}});
vm.runInContext(source,context);
vm.runInContext(`
 initOperationsAccess=async()=>({});_operationsCanView=()=>true;_operationsCanAddBuilderVehicle=()=>false;
 _operationsRenderProjectionPanel=()=>{};_operationsBindRowActions=()=>{};
 _operationsProjectGroupMarkup=(p,open)=>JSON.stringify({id:p.projectId,open,ids:p.vehicles.map(v=>v.vehicle_id)})+'\\n';
 _operationsSortActiveProjects=()=>0;
 _OPERATIONS.payload={vehicles:[]};_OPERATIONS.filter='started';
 _OPERATIONS.search={started:'Agency',active:'Unrelated',completed:'Unrelated'};
 _OPERATIONS.activeScheduleFilter='scheduled';
`,context);
context.anchor=anchor;
const vehicle=(id,acceptance='accepted',state='active')=>({vehicle_id:id,project_id:'p',agency_name:'Agency',acceptance_status:acceptance,project_state:state,schedule_bucket:'unscheduled'});
async function refresh(vehicleId='v1'){context.vehicleId=vehicleId;await vm.runInContext('initOperationsTab({followVehicleId:vehicleId,anchor})',context);}
const get=expression=>vm.runInContext(expression,context);
(async()=>{
 incoming={ok:true,vehicles:[vehicle('v1'),vehicle('v2')]};await refresh();
 assert.equal(hiddenDuringLoad,false);assert.equal(get('_OPERATIONS.filter'),'active');
 assert.equal(get('_OPERATIONS.search.active'),'');assert.equal(get('_OPERATIONS.search.started'),'Agency');
 assert.equal(get('_OPERATIONS.activeScheduleFilter'),'all');assert.equal(rendered[0].open,true);
 assert.equal(overrides[0].open,true);assert.equal(overrides[1].open,false);
 assert.equal(rowNodes.at(-1).getBoundingClientRect().top,350); // Same status row stays at the same screen coordinate.
 context.anchor=rowNodes.at(-1);
 incoming={ok:true,vehicles:[vehicle('v1','accepted','completed'),vehicle('v2','accepted','completed')]};await refresh();
 assert.equal(get('_OPERATIONS.filter'),'completed');assert.equal(rendered[0].open,true);assert.equal(overrides[0].open,true);
 assert.equal(rowNodes.at(-1).getBoundingClientRect().top,350);
 context.anchor=rowNodes.at(-1);
 incoming={ok:true,vehicles:[vehicle('v1'),vehicle('v2','not_accepted')]};await refresh();
 assert.equal(get('_OPERATIONS.filter'),'active');
 assert.deepEqual(rendered[0].ids,['v1']);
 assert.equal($('operations-active-count').textContent,1);
 assert.equal($('operations-started-count').textContent,1);
 await refresh('v2');
 assert.equal(get('_OPERATIONS.filter'),'started');
 assert.deepEqual(rendered[0].ids,['v2']);
 assert.equal(get('_OPERATIONS.search.started'),'Agency');
 const previous=rendered,scroll=window.scrollY;failed=true;await refresh();
 assert.equal(rendered,previous);assert.equal(window.scrollY,scroll);assert.equal($('operations-content').hidden,false);
 assert.equal(notices.at(-1)[0],'Offline');assert.equal(get('_OPERATIONS.loading'),false);
})().catch(error=>{console.error(error);process.exitCode=1;});
""")


def test_partial_acceptance_creates_started_and_active_vehicle_views():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const document={addEventListener(){}};
const context=vm.createContext({document,window:{},console,Set,Map});
vm.runInContext(source,context);
vm.runInContext(`
  _OPERATIONS.payload={vehicles:[
    {vehicle_id:'accepted',project_id:'p',project_state:'active',acceptance_status:'accepted'},
    {vehicle_id:'waiting',project_id:'p',project_state:'active',acceptance_status:'not_accepted'}
  ]};
`,context);
const views=vm.runInContext(`_operationsProjectViews({projectId:'p',vehicles:_OPERATIONS.payload.vehicles})`,context);
assert.equal(views.length,2);
assert.deepEqual(Array.from(views, view=>view.mode),['active','started']);
assert.deepEqual(Array.from(views[0].vehicles, vehicle=>vehicle.vehicle_id),['accepted']);
assert.deepEqual(Array.from(views[1].vehicles, vehicle=>vehicle.vehicle_id),['waiting']);
const activeButton={dataset:{operationsStatusScope:'project',operationsStatusId:'p',operationsStatusMode:'active'}};
const startedButton={dataset:{operationsStatusScope:'project',operationsStatusId:'p',operationsStatusMode:'started'}};
context.activeButton=activeButton;context.startedButton=startedButton;
assert.deepEqual(Array.from(vm.runInContext('_operationsQuickVehicles(activeButton)',context), vehicle=>vehicle.vehicle_id),['accepted']);
assert.deepEqual(Array.from(vm.runInContext('_operationsQuickVehicles(startedButton)',context), vehicle=>vehicle.vehicle_id),['waiting']);
""")


def test_projects_partial_acceptance_belongs_to_both_lists():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const context=vm.createContext({window:{},document:{addEventListener(){}},console,Set,Map});
vm.runInContext(source,context);
vm.runInContext(`
  _PT={operationsSnapshotReady:true,projectListStatusById:{},operationsByProject:{p:[
    {vehicle_id:'accepted',acceptance_status:'accepted'},
    {vehicle_id:'waiting',acceptance_status:'not_accepted'}
  ]}};
  project={project_id:'p',project_status:'active',build_units:[{individuals:[
    {individual_id:'accepted'},{individual_id:'waiting'}
  ]}]};
`,context);
assert.deepEqual(Array.from(vm.runInContext('_ptProjectListStatuses(project)',context)),['started','active']);
assert.equal(vm.runInContext('_ptProjectListStatus(project)',context),'started');
assert.deepEqual(Array.from(vm.runInContext('_ptProjectVehiclesForList(project,"active")',context), vehicle=>vehicle.vehicle_id),['accepted']);
assert.deepEqual(Array.from(vm.runInContext('_ptProjectVehiclesForList(project,"started")',context), vehicle=>vehicle.vehicle_id),['waiting']);
""", "projects/list_view.js")


def test_quick_and_modal_status_saves_pass_the_original_vehicle_and_anchor():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:true,classList:{add(){},remove(){}},removeAttribute(){}});return nodes.get(id);};
const button={dataset:{operationsStatusScope:'vehicle',operationsStatusId:'v1',operationsStatusWorkstream:'shop',operationsStatusValue:'in_progress'},classList:{add(){}}};
const calls=[],context=vm.createContext({$,window:{},document:{addEventListener(){},querySelectorAll:()=>[button]},console,
 api:async()=>({ok:true,changed:true,revision:2}),toast(){},confirm:()=>true,button,calls});
vm.runInContext(source,context);
vm.runInContext(`
 _OPERATIONS.payload={vehicles:[{vehicle_id:'v1',project_id:'p',shop_status:'not_started',revision:1}]};
 _operationsTransitionNeedsCorrection=()=>false;_operationsRequestId=()=> 'request-id';
 initOperationsTab=async options=>calls.push(options);
 _operationsEditableWorkstreams=()=>[_operationsStatusDef('shop')];
 _operationsRenderStatusEditor=()=>{};_operationsUpdateStatusGuidance=()=>{};_operationsEscAttr=x=>x;esc=x=>x;
`,context);
(async()=>{
 await vm.runInContext('_operationsApplyQuickStatus(button)',context);
 assert.equal(calls[0].followVehicleId,'v1');assert.equal(calls[0].anchor,button);
 vm.runInContext('_operationsOpenStatusEditor(_OPERATIONS.payload.vehicles,"Unit",{workstream:"shop",anchor:button})',context);
 $('operations-status-workstream').value='shop';$('operations-status-value').value='complete';
 await vm.runInContext('_operationsApplyStatus({preventDefault(){}})',context);
 assert.equal(calls[1].followVehicleId,'v1');assert.equal(calls[1].anchor,button);
 assert.equal(vm.runInContext('_OPERATIONS.editAnchor',context),null);
})().catch(error=>{console.error(error);process.exitCode=1;});
""")
