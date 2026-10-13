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
    {vehicle_id:'waiting',project_id:'p',project_state:'active',acceptance_status:'not_accepted'},
    {vehicle_id:'delivered',project_id:'p',project_state:'active',acceptance_status:'accepted',final_finish_status:'delivered'}
  ]};
`,context);
const views=vm.runInContext(`_operationsProjectViews({projectId:'p',vehicles:_OPERATIONS.payload.vehicles})`,context);
assert.equal(views.length,3);
assert.deepEqual(Array.from(views, view=>view.mode),['active','started','completed']);
assert.deepEqual(Array.from(views[0].vehicles, vehicle=>vehicle.vehicle_id),['accepted']);
assert.deepEqual(Array.from(views[1].vehicles, vehicle=>vehicle.vehicle_id),['waiting']);
assert.deepEqual(Array.from(views[2].vehicles, vehicle=>vehicle.vehicle_id),['delivered']);
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


def test_out_of_order_completion_needs_confirmation_but_not_a_note():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:true,textContent:'',className:'',disabled:false});return nodes.get(id);};
const context=vm.createContext({$,window:{},document:{addEventListener(){}},console,Set,Map});
vm.runInContext(source,context);
vm.runInContext(`
 _OPERATIONS.session={capabilities:['operations.shop.update','operations.correct']};
 _OPERATIONS.editVehicles=[{vehicle_id:'v1',shop_status:'',revision:1}];
 $('operations-status-workstream').value='shop';
 $('operations-status-value').value='complete';
`,context);
vm.runInContext('_operationsUpdateStatusGuidance()',context);
assert.equal($('operations-status-apply').disabled,false);
assert.equal($('operations-status-apply').textContent,'Confirm update');
assert.match($('operations-status-guidance').textContent,/no note is required/i);
assert.equal(nodes.has('operations-status-reason'),false);
""")


def test_vehicle_card_groups_statuses_and_collapses_secondary_actions():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const context=vm.createContext({
  window:{DTM_QUICKBOOKS_UI_ENABLED:true},document:{addEventListener(){}},console,Set,Map,
  esc:value=>String(value??''),estimateSendDetail:()=> 'Not sent',
  appHasCapability:capability=>['estimates.manage','operations.schedule.update'].includes(capability),
});
vm.runInContext(source,context);
vm.runInContext(`
 _OPERATIONS.session={operations_write_ready:true,capabilities:[
   'estimates.manage','operations.schedule.update','operations.parts.update'
 ]};
 vehicle={
   vehicle_id:'v1',project_id:'p1',vehicle_label:'Unit 21',unit_number:'21',vin:'VIN123',
   project_type:'build',project_state:'active',acceptance_status:'accepted',schedule_bucket:'scheduled',
   vehicle_availability_status:'at_dtm',parts_status:'parts_ready',shop_status:'in_progress',
   tray_status:'not_ready',programming_qc_status:'ready',final_finish_status:'not_ready',
   applicable_workstreams:['parts','programming_qc'],qbo_estimate_id:'44',qbo_estimate_number:'1004',
   accepted_date:'2026-09-01',vehicle_at_dtm_date:'2026-09-12',parts_ready_at:'2026-09-15',
   shop_started_at:'2026-09-16',planned_start_date:'2026-09-16',target_finish_date:'2026-10-01',
   must_deliver_by_date:'2026-10-04',build_team_names:['Blue Team'],updated_at:'2026-10-13T12:00:00Z'
 };
 markup=_operationsVehicleMarkup(vehicle);
 vehicle.qbo_estimate_id='';vehicle.qbo_estimate_number='';
 markupWithoutQuote=_operationsVehicleMarkup(vehicle);
`,context);
const markup=vm.runInContext('markup',context);
const markupWithoutQuote=vm.runInContext('markupWithoutQuote',context);
assert.match(markup,/operations-vehicle-kicker[^>]*>Vehicle/);
assert.match(markup,/Workflow status/);
assert.doesNotMatch(markup,/Key dates &amp; records/);
assert.match(markup,/operations-status-tone-complete/);
assert.match(markup,/operations-status-tone-unavailable/);
assert.match(markup,/operations-pill-quote[^>]*[^]*Quote 1004/);
assert.match(markup,/operations-pill-quote[^>]*data-operations-estimate-vehicle="v1"/);
assert.match(markup,/operations-pill-accepted[^>]*data-operations-accepted-date="v1"/);
assert.match(markup,/operations-pill-schedule[^>]*data-calendar-vehicle="v1"/);
assert.ok(markup.indexOf('<h3>Unit 21</h3>') < markup.indexOf('Quote 1004'));
assert.ok(markup.indexOf('Quote 1004') < markup.indexOf('operations-badges'));
assert.match(markup,/Build team<\/b>Blue Team/);
assert.match(markup,/Sep 12, 2026/);
assert.match(markup,/operations-action-menu-popover/);
assert.match(markup,/> Actions<\/summary>/);
assert.match(markup,/<strong>Manage estimate<\/strong>/);
assert.match(markup,/<strong>View history<\/strong>/);
assert.doesNotMatch(markup,/class="btn btn-secondary btn-sm"[^>]*data-calendar-vehicle/);
assert.match(markupWithoutQuote,/operations-connect-estimate-header[^>]*data-operations-estimate-vehicle="v1"[^>]*>Connect estimate/);
assert.doesNotMatch(markupWithoutQuote,/<strong>Connect estimate<\/strong>/);
""")


def test_collapsed_project_header_shows_one_quote_status_and_distinct_work_type():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const context=vm.createContext({
  window:{DTM_QUICKBOOKS_UI_ENABLED:true},document:{addEventListener(){}},console,Set,Map,
  esc:value=>String(value??''),estimateGroupStatus:()=>({key:'estimate-mixed',label:'1/2 Estimates Connected'}),
});
vm.runInContext(source,context);
vm.runInContext(`
 _OPERATIONS.session={capabilities:['estimates.manage']};
 _operationsEditableWorkstreams=()=>[];_operationsCanSchedule=()=>false;
 _operationsVehicleMarkup=()=>'';
 vehicles=[
   {vehicle_id:'v1',project_id:'p1',project_type:'service',project_state:'active',acceptance_status:'accepted',schedule_bucket:'unscheduled',qbo_estimate_id:'44'},
   {vehicle_id:'v2',project_id:'p1',project_type:'service',project_state:'active',acceptance_status:'accepted',schedule_bucket:'unscheduled',qbo_estimate_id:''}
 ];
 markup=_operationsProjectGroupMarkup({projectId:'p1',mode:'active',vehicles,allVehicles:vehicles},false);
 vehicles[1].qbo_estimate_id='45';
 completeMarkup=_operationsProjectGroupMarkup({projectId:'p1',mode:'active',vehicles,allVehicles:vehicles},false);
`,context);
const markup=vm.runInContext('markup',context),complete=vm.runInContext('completeMarkup',context);
assert.match(markup,/project-type-badge-service[^>]*>Service/);
assert.match(markup,/<strong>[^<]+<\/strong>\s*<span class="operations-project-type-row">/);
assert.match(markup,/operations-quote-status-missing[^>]*data-operations-estimate-vehicle="v2"[^>]*>1\/2 quotes need connection/);
assert.doesNotMatch(markup,/1\/2 Estimates Connected/);
assert.match(complete,/operations-quote-status-complete[^>]*>All quotes connected/);
""")


def test_operations_save_retries_non_overlapping_revision_changes_without_overwriting():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const responses=[
  {ok:false,conflict:true},
  {ok:true,vehicles:[{vehicle_id:'v1',revision:8,shop_status:'not_started',parts_status:'received'}]},
  {ok:true,changed:true,revision:9},
];
const calls=[];
const context=vm.createContext({window:{},document:{addEventListener(){}},console,Set,Map,
  api:async(path,body)=>{calls.push({path,body});return responses.shift();}});
vm.runInContext(source,context);
context.vehicle={vehicle_id:'v1',revision:4,shop_status:'not_started',parts_status:'ordered'};
(async()=>{
  const result=await vm.runInContext(`_operationsSaveWithConflictRecovery('/api/operations/status',{
    vehicle_id:'v1',workstream:'shop',new_status:'complete',expected_revision:4,request_id:'first'
  },vehicle,[{field:'shop_status',label:'Build / Shop',before:'not_started',after:'complete'}])`,context);
  assert.equal(result.ok,true);
  assert.equal(calls.length,3);
  assert.equal(calls[2].body.expected_revision,8);
  assert.notEqual(calls[2].body.request_id,'first');
  assert.equal(context.vehicle.parts_status,'received');
})().catch(error=>{console.error(error);process.exitCode=1;});
""")


def test_shared_modal_guardrails_normalize_dialogs_and_route_escape_to_owner():
    run_ui(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const attrs=new Map(),close={type:'',disabled:false,clicks:0,click(){this.clicks++;}};
const title={id:''};
const overlay={id:'sample-modal',
 setAttribute(key,value){attrs.set(key,value);},hasAttribute(key){return attrs.has(key);},
 querySelector(selector){return selector.includes('modal-title')?title:close;},
 querySelectorAll(){return [close];},
};
const listeners={};
const document={
 addEventListener(type,fn){(listeners[type]??=[]).push(fn);},
 getElementById(){return null;},
 querySelectorAll(selector){return selector==='.modal-overlay.open'?[overlay]:[overlay];},
};
const context=vm.createContext({document,window:{},console,Map,Set,fetch:()=>Promise.resolve(),setTimeout,clearTimeout,setInterval:()=>0,navigator:{}});
vm.runInContext(source,context);
vm.runInContext('normalizeModalOverlay',context)(overlay);
assert.equal(attrs.get('role'),'dialog');assert.equal(attrs.get('aria-modal'),'true');
assert.equal(attrs.get('aria-labelledby'),'sample-modal-title');assert.equal(close.type,'button');
const event={key:'Escape',defaultPrevented:false,preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;}};
listeners.keydown[0](event);
assert.equal(close.clicks,1);assert.equal(event.prevented,true);assert.equal(event.stopped,true);
""", "api.js")
