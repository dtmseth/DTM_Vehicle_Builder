// Calendar owns planning; Operations owns production status and delivery deadlines.
(() => {
  const sheet=document.createElement('link');sheet.rel='stylesheet';sheet.href='/ui/calendar.css';document.head.append(sheet);
  const state = {data:null, view:'week', date:new Date(), selected:null, preview:null, edit:null, busy:false, request:0, saving:false, saveId:null, polling:false, teamFilter:'', queueMode:'unscheduled', choices:[], choiceRequest:0, overlapApproval:null};
  const colors = ['blue','purple','teal','orange','rose','slate'];
  const kinds = {checks:'Final checks',strip_build:'Strip + build',build:'Build only',strip:'Strip only',service:'Service',offsite:'Off-site work'};
  const federalHolidays = [['new_years_day',"New Year's Day"],['martin_luther_king_jr_day','Martin Luther King Jr. Day'],['washingtons_birthday',"Washington's Birthday"],['memorial_day','Memorial Day'],['juneteenth','Juneteenth'],['independence_day','Independence Day'],['labor_day','Labor Day'],['columbus_day',"Columbus / Indigenous Peoples' Day"],['veterans_day','Veterans Day'],['thanksgiving_day','Thanksgiving Day'],['christmas_day','Christmas Day']];
  const federalHolidayIds = settings => Array.isArray(settings.us_federal_holidays) ? settings.us_federal_holidays : settings.use_us_federal_holidays===false ? [] : federalHolidays.map(([id])=>id);
  const canEdit = () => appHasCapability('operations.schedule.update');
  const text = value => _operationsEscAttr(value);
  const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const day = value => new Date(String(value).slice(0,10)+'T12:00:00');
  const add = (d,n) => {const x=new Date(d);x.setDate(x.getDate()+n);return x;};
  const label = value => value ? day(value).toLocaleDateString(undefined,{month:'short',day:'numeric'}) : '—';
  const dateTime = value => value ? `${label(value)}, ${new Date(value).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})}` : '—';
  const message = value => { $('calendar-message').textContent=value; };
  const btn = (name,id,primary=false) => `<button type="button" class="btn ${primary?'btn-primary':'btn-secondary'} btn-sm" id="${id}">${name}</button>`;

  const vehicleName = j => (j.vehicle_label||j.title||'').split(/\s+-\s+|\s+·\s+/).filter(part=>
    !/^(VIN\b|No VIN\b|Pending ID\b|Unit (not set|unknown)\b)/i.test(part) && (!j.vin||!part.includes(j.vin))).join(' · ') || `Vehicle ${j.build_number||1}`;
  function statusEntries(j){
    if(!j||j.custom)return [];
    const parts={ordered:['Parts ordered','blue'],received:['Parts received','green'],parts_ready:['Parts ready','green']};
    const vehicles={awaiting_details:['Awaiting vehicle details','slate'],waiting_on_dealer:['Waiting on dealer','amber'],waiting_on_agency:['Waiting on agency','amber'],ready_for_pickup:['Ready for pickup','blue'],at_dtm:['Vehicle at DTM','green'],delivered:['Vehicle delivered','green']};
    const badges=[j.project_type&&j.project_type!=='build'&&j.service_details?.requires_parts===false?['Parts not needed','slate']:parts[j.parts_status]||['Parts not ordered','slate'],j.project_type==='offsite'&&j.vehicle_availability_status==='ready_for_pickup'?['Available on site','green']:vehicles[j.vehicle_availability_status]||['Vehicle status unknown','slate']];
    badges.unshift([projectTypeLabel(j),'slate']);
    if(j.shop_status==='in_progress')badges.push(['Build in progress','amber']);
    if(j.shop_status==='complete')badges.push(['Build completed'+(j.shop_completed_at?' · '+label(j.shop_completed_at):''),'green']);
    if(['ready_for_delivery','delivered'].includes(j.final_finish_status))badges.push([j.final_finish_status==='delivered'?'Delivered'+(j.delivered_date?' · '+label(j.delivered_date):''):'Ready for delivery'+(j.ready_for_delivery_at?' · '+label(j.ready_for_delivery_at):''),'green']);
    return badges;
  }
  function projectTypeLabel(j){return ({build:'Build',service:'Service',offsite:'Off-Site Service'})[j.project_type||'build']||'Build';}
  function statusBadges(j){return renderStatusBadges(statusEntries(j));}
  function renderStatusBadges(badges){
    return '<span class="calendar-status-badges">'+badges.map(([name,color])=>`<span class="calendar-status-badge calendar-status-${color}">${text(name)}</span>`).join('')+'</span>';
  }
  function projectStatusBadges(jobs){
    const counts=new Map();
    jobs.forEach(job=>statusEntries(job).forEach(([name,color])=>{
      const key=JSON.stringify([name,color]);counts.set(key,(counts.get(key)||0)+1);
    }));
    return renderStatusBadges([...counts].map(([key,count])=>{
      const [name,color]=JSON.parse(key);return [name+(count<jobs.length?` · ${count}/${jobs.length}`:''),color];
    }));
  }
  const bookingWarnings=j=>[...(j?.blocked||[]),...(j?.warnings||[])].filter(x=>!/forecast|build in progress/i.test(x));

  $('tab-calendar').innerHTML = `<div class="card calendar-shell">
    <div id="calendar-message" class="calendar-message" role="status">Loading Calendar…</div>
    <div id="calendar-legend" class="calendar-legend"></div>
    <div class="calendar-workspace"><aside id="calendar-queue" class="calendar-queue" aria-label="Acceptance queue"></aside>
      <section class="calendar-main" aria-label="Schedule"><div class="calendar-grid-toolbar">
        <div class="calendar-navigation"><h2 id="calendar-range">Calendar</h2>${btn('‹','calendar-prev')}${btn('Today','calendar-today')}${btn('›','calendar-next')}${btn('Refresh','calendar-refresh')}${btn('Retry date update','calendar-review',true)}</div>
        <div class="calendar-controls calendar-view-controls">${btn('Week','calendar-week')}${btn('Month','calendar-month')}<input id="calendar-month-picker" type="month" aria-label="Go to month"><select id="calendar-team-filter" aria-label="Show team"></select><div id="calendar-next-opening" class="calendar-next-opening" role="status">Calculating next opening…</div></div>
      </div><div id="calendar-board" class="calendar-board"></div></section>
    </div>
    <div id="calendar-attention" class="calendar-attention"></div>
    <div class="calendar-key"><span><i class="calendar-key-waiting"></i>Waiting on parts or vehicle</span><span><i class="calendar-key-ready"></i>Parts and vehicle ready</span><span><i class="calendar-key-started"></i>Build in progress</span><span><i class="calendar-key-blackout"></i>Shop closed</span><span id="calendar-buffer"></span></div>
  </div>
  <div class="modal-overlay calendar-bubble-overlay" id="calendar-detail-overlay" hidden><section id="calendar-detail" class="modal calendar-detail" hidden role="dialog" aria-modal="true" aria-labelledby="calendar-detail-title" tabindex="-1"></section></div>
  <div class="modal-overlay calendar-bubble-overlay" id="calendar-choice-modal" role="dialog" aria-modal="true" aria-labelledby="calendar-choice-title" hidden><div class="modal calendar-detail"><h3 id="calendar-choice-title"></h3><p id="calendar-choice-message"></p><div class="modal-actions">${btn('Cancel','calendar-choice-cancel')}${btn('Continue','calendar-choice-accept',true)}</div></div></div>
  <div class="modal-overlay" id="calendar-review-modal" role="dialog" aria-modal="true" aria-labelledby="calendar-review-title" hidden>
    <div class="modal calendar-review-modal"><div class="modal-header"><span id="calendar-review-title">Resolve shared schedule changes</span>${btn('×','calendar-review-close')}</div>
    <div id="calendar-review-body"></div><label class="calendar-reason">Explanation<textarea id="calendar-review-reason" maxlength="1000" placeholder="Why the booking is changing, or why the risk is acceptable"></textarea></label><div id="calendar-review-message" role="status"></div>
    <div class="modal-actions">${btn('Cancel','calendar-review-cancel')}${btn('Save schedule','calendar-review-save',true)}</div></div></div>`;

  const expandedProjects=new Set();
  $('calendar-choice-accept').insertAdjacentHTML('beforebegin',btn('Replace booking','calendar-choice-alternative'));
  ['calendar-detail-overlay','calendar-review-modal','calendar-choice-modal'].forEach(id=>document.body.append($(id)));
  let returnFocus=null;
  function showBubble(kind){
    returnFocus=document.activeElement;
    const panel=$('calendar-detail');
    $( 'calendar-'+kind+'-overlay').hidden=false;$( 'calendar-'+kind+'-overlay').classList.add('open');panel.hidden=false;panel.focus();
  }
  function closeBubble(kind){
    const overlay=$('calendar-'+kind+'-overlay');overlay.hidden=true;overlay.classList.remove('open');
    $('calendar-detail').hidden=true;
    if(returnFocus?.isConnected)returnFocus.focus();
  }
  ['detail'].forEach(kind=>$('calendar-'+kind+'-overlay').onclick=e=>{if(e.target===e.currentTarget)closeBubble(kind);});
  document.addEventListener('keydown',e=>{
    const overlay=['calendar-choice-modal','calendar-review-modal','calendar-detail-overlay'].map($).find(el=>!el.hidden);
    if(!overlay||document.querySelector('.modal-overlay.open:not([id^="calendar-"])'))return;
    if(e.key==='Escape'){e.preventDefault();if(overlay.id==='calendar-choice-modal')finishChoice(false);else if(overlay.id==='calendar-review-modal')closeReview();else closeBubble('detail');}
    if(e.key==='Tab'){
      const items=[...overlay.querySelectorAll('button,input,select,textarea,summary,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);
      const first=items[0],last=items.at(-1);if(!first)return;
      if(e.shiftKey&&(document.activeElement===first||!items.includes(document.activeElement))){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&(document.activeElement===last||!items.includes(document.activeElement))){e.preventDefault();first.focus();}
    }
  });
  let choiceResolve=null;
  function finishChoice(accepted){$('calendar-choice-modal').hidden=true;$('calendar-choice-modal').classList.remove('open');const done=choiceResolve;choiceResolve=null;done?.(accepted);if(!$('calendar-detail').hidden)$('calendar-detail').focus();}
  function askCalendar(title,body,accept='Continue',alternative=''){
    $('calendar-choice-title').textContent=title;$('calendar-choice-message').textContent=body;$('calendar-choice-accept').textContent=accept;
    $('calendar-choice-alternative').hidden=!alternative;$('calendar-choice-alternative').textContent=alternative;
    $('calendar-choice-modal').hidden=false;$('calendar-choice-modal').classList.add('open');$('calendar-choice-cancel').focus();
    return new Promise(resolve=>{choiceResolve=resolve;});
  }
  $('calendar-choice-cancel').onclick=()=>finishChoice(false);$('calendar-choice-accept').onclick=()=>finishChoice(true);
  $('calendar-choice-alternative').onclick=()=>finishChoice('replace');
  // Pointer dragging works in native WebViews as well as browsers. Full day cells
  // are targets. Saves still use the server's preview ticket and revision checks.
  let drag=null,suppressClickUntil=0;
  const insertLine=document.createElement('div');insertLine.className='calendar-insert-line';insertLine.hidden=true;document.body.append(insertLine);
  function dragPlacement(target,x){
    if(!target||target.disabled)return null;
    if(!target.dataset.dropJob)return {kind:'new',edge:null};
    const rect=target.getBoundingClientRect(),margin=Math.min(14,rect.width/4);
    const edge=x<rect.left+margin?'before':x>rect.right-margin?'after':null;
    return {kind:edge?'insert':'replace',edge};
  }
  function showDragPlacement(target,placement){
    drag.target?.classList.remove('calendar-drop-replace','calendar-drop-new');
    insertLine.hidden=true;
    if(placement?.kind==='insert')({target,placement}=canonicalInsertion(target,placement));
    drag.target=target;drag.placement=placement;
    if(!placement){drag.ghost.textContent=drag.label;delete drag.ghost.dataset.dropState;return;}
    if(placement.kind==='insert'){
      const rect=target.getBoundingClientRect();
      insertLine.style.left=`${placement.lineX??(placement.edge==='before'?rect.left-3:rect.right+3)}px`;
      insertLine.style.top=`${rect.top-4}px`;insertLine.style.height=`${rect.height+8}px`;insertLine.hidden=false;
    }else target.classList.add('calendar-drop-'+placement.kind);
    drag.ghost.dataset.dropState=placement.kind;
    const projectMove=drag.node?.dataset.projectId;
    drag.ghost.textContent=`${{insert:'Insert between builds',replace:'Replace this booking',new:'New booking'}[placement.kind]}${projectMove?' · '+(drag.unitOnly?'Selected unit':'Whole project'):''} · ${drag.label}`;
  }
  function canonicalInsertion(target,placement){
    const rect=target.getBoundingClientRect(),surface=target.closest('.calendar-lane,.calendar-month-week');
    const cards=[...(surface?.querySelectorAll('[data-drop-job]')||[])].filter(card=>card!==target&&card.dataset.team===target.dataset.team);
    const before=placement.edge==='before';
    const neighbor=cards.find(card=>{const r=card.getBoundingClientRect();return Math.abs(r.top-rect.top)<2&&Math.abs(before?r.right-rect.left:r.left-rect.right)<=12;});
    if(!neighbor)return {target,placement:drag.value==='vehicle:'+target.dataset.dropJob?null:placement};
    const left=before?neighbor:target,right=before?target:neighbor;
    const lineX=(left.getBoundingClientRect().right+right.getBoundingClientRect().left)/2;
    // Both sides of a handoff use the same anchor, including when the right
    // card is the unit being dragged. Never show a red line that drops on itself.
    if(drag.value==='vehicle:'+left.dataset.dropJob)return {target:right,placement:{kind:'insert',edge:'before',lineX}};
    return {target:left,placement:{kind:'insert',edge:'after',lineX}};
  }
  function draggable(node,value){
    node.draggable=false;node.classList.add('calendar-draggable');
    node.addEventListener('pointerdown',e=>{if(e.button!==0||!canEdit()||state.busy)return;closeCalendarMenu();drag={value,x:e.clientX,y:e.clientY,node,active:false,unitOnly:e.shiftKey,label:node.querySelector('strong')?.textContent||node.textContent};});
    node.addEventListener('click',e=>{if(Date.now()<suppressClickUntil){e.preventDefault();e.stopImmediatePropagation();}},true);
  }
  document.addEventListener('pointermove',e=>{
    if(!drag)return;
    drag.unitOnly=e.shiftKey;
    if(!drag.active&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<6)return;
    e.preventDefault();
    if(!drag.active){drag.active=true;drag.ghost=document.createElement('div');drag.ghost.className='calendar-drag-ghost';drag.ghost.textContent=drag.node.querySelector('strong')?.textContent||drag.node.textContent;document.body.append(drag.ghost);document.body.classList.add('calendar-dragging');}
    drag.ghost.style.left=(e.clientX+12)+'px';drag.ghost.style.top=(e.clientY+12)+'px';
    const hit=document.elementFromPoint(e.clientX,e.clientY);
    const surface=hit?.closest('.calendar-lane,.calendar-month-week');
    let target=hit?.closest('[data-calendar-drop]');
    if(!target?.dataset.dropJob){
      // The narrow visual gap at a handoff belongs to the adjacent booking edge.
      const edge=[...(surface?.querySelectorAll('[data-drop-job]')||[])].find(card=>{const r=card.getBoundingClientRect();return e.clientY>=r.top&&e.clientY<r.bottom&&(Math.abs(e.clientX-r.left)<=8||Math.abs(e.clientX-r.right)<=8);});
      target=edge||target||[...(surface?.querySelectorAll('[data-calendar-drop]')||[])].find(cell=>{const r=cell.getBoundingClientRect();return e.clientX>=r.left&&e.clientX<r.right&&e.clientY>=r.top&&e.clientY<r.bottom;});
    }
    showDragPlacement(target,dragPlacement(target,e.clientX));
  },{passive:false});
  function endDrag(cancel=false){
    if(!drag)return;const current=drag;drag=null;current.ghost?.remove();insertLine.hidden=true;current.target?.classList.remove('calendar-drop-replace','calendar-drop-new');document.body.classList.remove('calendar-dragging');
    if(current.active){suppressClickUntil=Date.now()+300;if(!cancel&&current.placement)stageDrop(current.value,current.target.dataset.team||state.teamFilter,current.target.dataset.date,current.target.dataset.dropJob,current.placement.edge,current.unitOnly);}
  }
  document.addEventListener('pointerup',event=>{if(drag)drag.unitOnly=event.shiftKey;endDrag();});document.addEventListener('pointercancel',()=>endDrag(true));window.addEventListener('blur',()=>endDrag(true));
  function dropTarget(node,team,date){
    node.dataset.calendarDrop='';node.dataset.team=team;node.dataset.date=date;
  }
  async function request(path, body) {const result=await api(path,body);if(!result?.ok)throw new Error(result?.error||'Calendar could not load. Try Refresh.');return result;}
  window.initCalendarTab = async function(quiet=false) {
    const seq=++state.request;pollSave();
    if(!quiet)message('Loading Calendar…');
    try {const data=await request('/api/calendar');if(seq!==state.request)return;state.data=data;render();state.refreshDetail?.();message(`${data.local_only?'Local preview · ':''}${data.plan.jobs.length} reservations · ${data.plan.queue.length} accepted vehicles awaiting scheduling`);}
    catch(e){if(seq===state.request)message(e.message);}
  };
  new ResizeObserver(()=>{const main=$('calendar-board').parentElement;if(main.offsetHeight)$('calendar-queue').style.height=window.innerWidth>850?`${main.offsetHeight}px`:'280px';}).observe($('calendar-board').parentElement);
  function render() {
    if(!state.data)return;
    const {settings,plan}=state.data;
    renderQueue();
    $('calendar-team-filter').innerHTML='<option value="">All teams</option>'+settings.teams.filter(t=>t.active).map(t=>`<option value="${text(t.id)}" ${state.teamFilter===t.id?'selected':''}>${text(t.name)}</option>`).join('');
    $('calendar-review').hidden=!canEdit()||(!state.syncFailed&&(state.saving||!state.data.pending_date_count));
    $('calendar-review').textContent=state.syncConflict?'Review sync conflict':state.syncFailed?'Retry sync':'Retry date update';
    const opening=(state.data.next_openings||[]).filter(o=>!state.teamFilter||o.team_id===state.teamFilter).sort((a,b)=>a.start.localeCompare(b.start))[0];
    $('calendar-next-opening').textContent=opening?`Next opening · ${opening.team_name} · ${label(opening.start)}`:'Next opening · '+(state.data.opening_note==='Standard strip + build'?'None available':state.data.opening_note||'Unavailable');
    $('calendar-next-opening').title=state.data.opening_note||'';
    $('calendar-week').classList.toggle('btn-primary',state.view==='week');
    $('calendar-month').classList.toggle('btn-primary',state.view==='month');
    $('calendar-week').classList.toggle('btn-secondary',state.view!=='week');
    $('calendar-month').classList.toggle('btn-secondary',state.view!=='month');
    $('calendar-week').setAttribute('aria-pressed',state.view==='week');
    $('calendar-month').setAttribute('aria-pressed',state.view==='month');
    $('calendar-month-picker').value=iso(state.date).slice(0,7);
    $('calendar-legend').innerHTML=settings.teams.filter(t=>t.active||plan.jobs.some(j=>j.team_id===t.id)).map(t=>`<span class="calendar-color-${text(t.color)}"><i class="calendar-dot"></i>${text(t.name)} · ${t.people} ${t.people===1?'person':'people'}</span>`).join('');
    $('calendar-buffer').textContent=`${settings.buffer_percent}% weekly capacity reserve`;
    const board=$('calendar-board');board.replaceChildren();
    if(state.view==='week')renderWeek(board);else renderMonth(board);
    const attention=$('calendar-attention');attention.replaceChildren();
    plan.needs_review.forEach(j=>{const b=document.createElement('button');b.className='btn btn-secondary btn-sm';b.textContent=`${j.title||j.agency_name} · ${j.reason}`;b.onclick=()=>openJob(j.id);attention.append(b);});
    plan.warnings.forEach(w=>{const p=document.createElement('p');p.textContent=w;attention.append(p);});
  }
  function renderQueue(){
    const host=$('calendar-queue'),scrollTop=host.scrollTop;host.replaceChildren();
    const title=document.createElement('h3');title.textContent='Acceptance order';host.append(title);
    const mode=document.createElement('select');mode.setAttribute('aria-label','Acceptance queue filter');mode.innerHTML='<option value="unscheduled">Unscheduled</option><option value="all">All accepted</option>';mode.value=state.queueMode;mode.onchange=()=>{state.queueMode=mode.value;renderQueue();};host.append(mode);
    const groups=new Map();(state.queueMode==='all'?state.data.plan.accepted_queue:state.data.plan.queue).forEach(j=>{if(!groups.has(j.project_id))groups.set(j.project_id,[]);groups.get(j.project_id).push(j);});
    if(!groups.size){const p=document.createElement('p');p.textContent='All dated accepted vehicles are reserved.';host.append(p);}
    groups.forEach((jobs,project)=>{
      const group=document.createElement('details');group.className='calendar-queue-project';group.open=expandedProjects.has(project);group.dataset.projectId=project;
      group.addEventListener('toggle',()=>{if(group.isConnected){if(group.open)expandedProjects.add(project);else expandedProjects.delete(project);}});
      const ready=jobs.filter(j=>!j.blocked?.length).length,scheduled=jobs.filter(j=>!j.unscheduled).length;
      const heading=document.createElement('summary');heading.innerHTML=`<strong>${text(jobs[0].agency_name||jobs[0].title)}</strong><span>${jobs.length} unit${jobs.length===1?'':'s'} · Accepted ${label(jobs[0].accepted_date)}</span>${projectStatusBadges(jobs)}<small>${ready} ready${scheduled?' · '+scheduled+' scheduled':''} · Expand for individual units</small>`;group.append(heading);
      if(canEdit()&&jobs.some(j=>j.unscheduled))draggable(heading,'project:'+project);
      const projectButton=document.createElement('button');projectButton.type='button';projectButton.className='btn btn-secondary btn-sm calendar-project-open';projectButton.textContent='View whole project';projectButton.onpointerdown=e=>e.stopPropagation();projectButton.onclick=e=>{e.preventDefault();e.stopPropagation();openProject(project);};heading.append(projectButton);
      jobs.forEach(j=>{const button=document.createElement('button');button.type='button';button.className='btn btn-secondary btn-sm calendar-queue-vehicle';
        button.innerHTML=`<strong>${text(vehicleName(j))}</strong>${statusBadges(j)}<small>Accepted ${label(j.accepted_date)}${j.unscheduled?'':' · Scheduled '+label(j.start)}</small>`;
        button.classList.toggle('calendar-queue-scheduled',!j.unscheduled);
        button.dataset.vehicleId=j.id;button.onclick=()=>openJob(j.id);
        if(!j.unscheduled)button.title='Already scheduled · Click to view booking';
        if(canEdit()&&j.unscheduled)draggable(button,'vehicle:'+j.id);group.append(button);});
      host.append(group);
    });
    host.scrollTop=scrollTop;
  }
  async function stageDrop(value,team,date,targetId=null,edge=null,unitOnly=false){
    if(!canEdit())return;
    const project=value.startsWith('project:');
    const id=project?state.data.plan.queue.find(j=>j.project_id===value.slice(8))?.id:value.slice(8);
    if(!id||id===targetId)return;
    const source=state.data.plan.jobs.find(j=>j.id===id),target=state.data.plan.jobs.find(j=>j.id===targetId);
    if(source&&!source.custom&&source.project_id&&!unitOnly){
      return openDropDialog(source,{id,mode:target?edge||'swap':'new',...(target?{target_id:target.id}:{team_id:team,start_date:date})});
    }
    if(target){
      const mode=edge||(source?'swap':'replace');
      return saveSchedule(null,{schedule_action:{id,target_id:target.id,mode,include_project:project},reason:mode==='swap'?'Swapped bookings by drag':mode==='replace'?'Replaced booking by drag':'Inserted booking by drag'});
    }
    if(team)return saveSchedule(null,{schedule_action:{id,team_id:team,start_date:date,mode:'new',include_project:project},reason:'Placed booking in open space'});
    const autoTeam=state.view==='month';
    if(value.startsWith('project:')){
      const vehicle=state.data.plan.queue.find(j=>j.project_id===value.slice(8));
      if(vehicle)openJob(vehicle.id,{team,date,autoTeam,includeProject:true});else message('This project has no unscheduled vehicles. Open a booking to move it.');
    }else if(value.startsWith('vehicle:'))openJob(value.slice(8),{team,date,autoTeam});
  }
  function visibleJobs(){return state.data.plan.jobs.filter(j=>!state.teamFilter||(j.team_ids||[j.team_id]).includes(state.teamFilter));}
  function teamRows(){return state.data.settings.teams.filter(t=>(!state.teamFilter||t.id===state.teamFilter)&&(t.active||state.data.plan.jobs.some(j=>(j.team_ids||[j.team_id]).includes(t.id))));}
  const isClosedDate=date=>state.data?.closed_dates?.includes(date);
  function bookingSpan(segments,dates){
    const hits=segments.filter(s=>dates.includes(s.date));if(!hits.length)return null;
    const first=dates.indexOf(hits[0].date),last=dates.indexOf(hits[hits.length-1].date);
    return {start:first+(hits[0].start_hour-8)/state.data.settings.hours_per_day,
      end:last+(hits[hits.length-1].end_hour-8)/state.data.settings.hours_per_day};
  }
  function bookingRows(entries,dates){
    const ends=[],rows=entries.map(entry=>({...entry,span:bookingSpan(entry.segments,dates)})).filter(entry=>entry.span)
      .sort((a,b)=>a.span.start-b.span.start||b.span.end-a.span.end||a.job.id.localeCompare(b.job.id));
    for(const entry of rows){
      // Prefer the row whose previous build just ended, so a handoff remains
      // on that row even if an older overlapping build freed another row.
      const previous=Math.max(...ends.filter(end=>end<=entry.span.start+.0001));
      let row=ends.indexOf(previous);if(row<0)row=ends.length;ends[row]=entry.span.end;entry.row=row;
    }
    return {rows,count:ends.length};
  }
  function openScheduledBuild(job){
    if(job.custom||!job.project_id||state.data.split_projects?.includes(job.project_id))openJob(job.id);
    else openProject(job.project_id);
  }
  let calendarMenu=null,calendarMenuTrigger=null;
  function closeCalendarMenu(restoreFocus=false){
    calendarMenu?.remove();calendarMenu=null;
    if(restoreFocus&&calendarMenuTrigger?.isConnected)calendarMenuTrigger.focus({preventScroll:true});
    calendarMenuTrigger=null;
  }
  async function deleteScheduledBuild(job){
    const rows=state.data.plan.jobs.filter(j=>j.project_id===job.project_id&&!j.historical&&j.shop_status!=='complete');
    if(!job.custom&&rows.length>1){
      const scope=await askCalendar('Delete from schedule?', 'Remove the whole project or only the selected unit? Project records are kept.', 'Whole project', 'Selected unit only');
      if(!scope)return;
      return removeBooking(job.project_id,scope===true?null:job.id);
    }
    return removeBooking(job.project_id,job.id);
  }
  function calendarMenuActions(job){
    return [
      {label:'Open project',enabled:!job.custom&&!!job.project_id,run:()=>openProject(job.project_id)},
      {label:'Open unit',enabled:true,run:()=>openJob(job.id)},
      {label:'Delete from schedule…',enabled:canEdit()&&!state.busy&&!job.historical&&job.shop_status!=='complete',run:()=>deleteScheduledBuild(job)},
    ];
  }
  function openCalendarMenu(event,job,trigger){
    event.preventDefault();closeCalendarMenu();calendarMenuTrigger=trigger;
    const menu=document.createElement('div');menu.className='calendar-context-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','Calendar booking');
    calendarMenuActions(job).forEach(action=>{const button=document.createElement('button');button.type='button';button.textContent=action.label;button.disabled=!action.enabled;button.setAttribute('role','menuitem');button.onclick=()=>{closeCalendarMenu(true);action.run();};menu.append(button);});
    calendarMenu=menu;document.body.append(menu);
    const origin=trigger.getBoundingClientRect(),x=event.clientX||origin.left,y=event.clientY||origin.bottom;
    menu.style.left=Math.max(8,Math.min(x,window.innerWidth-menu.offsetWidth-8))+'px';
    menu.style.top=Math.max(8,Math.min(y,window.innerHeight-menu.offsetHeight-8))+'px';
    menu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
    menu.onkeydown=event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeCalendarMenu(true);}
      else if(event.key==='Tab')closeCalendarMenu(true);
      else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        event.preventDefault();const items=[...menu.querySelectorAll('button:not(:disabled)')],index=items.indexOf(document.activeElement);
        items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();
      }
    };
  }
  document.addEventListener('pointerdown',event=>{if(calendarMenu&&!calendarMenu.contains(event.target))closeCalendarMenu();});
  document.addEventListener('scroll',()=>closeCalendarMenu(),true);window.addEventListener('resize',()=>closeCalendarMenu());window.addEventListener('blur',()=>closeCalendarMenu());
  function booking(job,segments,dates,lane) {
    const span=bookingSpan(segments,dates);if(!span)return;
    const waiting=!job.custom&&!job.historical&&job.shop_status!=='complete'&&(job.blocked||[]).some(reason=>['Waiting on parts','Waiting on vehicle'].includes(reason));
    const started=job.kind!=='checks'&&job.shop_status==='in_progress';
    const deliveryReady=job.kind!=='checks'&&['ready_for_delivery','delivered'].includes(job.final_finish_status);
    const b=document.createElement('button');b.type='button';b.className=`calendar-booking calendar-color-${job.color}${waiting?' calendar-blocked':''}${started?' calendar-started':''}${deliveryReady?' calendar-delivery-ready':''}`;
    b.dataset.jobId=job.id;
    if(!job.custom)b.dataset.projectId=job.project_id;
    const part=state.view==='week';
    const {start,end}=span;
    b.style.setProperty('--calendar-left',`${start/dates.length*100}%`);
    b.style.setProperty('--calendar-width',`${(end-start)/dates.length*100}%`);
    const top=document.createElement('strong');const name=document.createElement('span');name.textContent=`${job.historical?'✓ ':''}${job.calendar_label||job.title}`;top.append(name);
    if(!job.custom){const type=document.createElement('span');type.className='project-type-badge';type.textContent=projectTypeLabel(job);top.append(type);}
    const vin=String(job.vin||'').trim(),vinEnding=!job.custom&&vin.length>=6?vin.slice(-6).toUpperCase():'';
    if(vinEnding){const suffix=document.createElement('span');suffix.className='calendar-vin-ending';suffix.textContent=vinEnding;suffix.title='VIN ending '+vinEnding;top.append(suffix);}
    if(!job.custom){const count=document.createElement('span');count.className='calendar-build-count';count.textContent=`${job.build_number}/${job.build_count}`;top.append(count);}b.append(top);
    if(canEdit()&&!job.historical&&job.shop_status!=='complete'&&job.kind!=='checks'){
      draggable(b,'vehicle:'+job.id);dropTarget(b,job.team_id,job.start.slice(0,10));b.dataset.dropJob=job.id;
      b.dataset.dropHint='Drag to move the whole project. Hold Shift to move only this unit. Red line: insert. Highlighted booking: swap. Open space: new booking.';
    }
    const milestone=job.kind==='checks'?'':job.final_finish_status==='delivered'?`Delivered${job.delivered_date?' · '+label(job.delivered_date):''}`:job.final_finish_status==='ready_for_delivery'?`Ready for delivery${job.ready_for_delivery_at?' · '+label(job.ready_for_delivery_at):''}`:job.shop_status==='complete'?`Build completed${job.shop_completed_at?' · '+label(job.shop_completed_at):''}`:'';
    if(part){const sub=document.createElement('small');sub.textContent=milestone||`${kinds[job.kind]} · ${job.hours} labor hours · Build ends ${label(job.end)} · Ready ${label(job.ready)}${job.deadline?' · Deadline '+label(job.deadline):''}`;b.append(sub);}
    else if(milestone)name.textContent+=` · ${milestone}`;
    const description=`${job.title}, ${job.team_name}, starts ${dateTime(job.start)}, build ends ${dateTime(job.end)}, ready ${dateTime(job.ready)}${job.deadline?', Deadline '+label(job.deadline):''}${started?', Build in progress':''}${deliveryReady?job.final_finish_status==='delivered'?', Delivered':', Ready for delivery':''}${waiting?', Waiting on parts or vehicle':''}`;
    b.setAttribute('aria-label',description+(vinEnding?', VIN ending '+vinEnding:'')+(milestone?'. '+milestone:''));b.title=description+(vinEnding?', VIN ending '+vinEnding:'')+(milestone?'. '+milestone:'')+(b.dataset.dropHint?'. '+b.dataset.dropHint:'');
    b.onclick=()=>openScheduledBuild(job);lane.append(b);
    b.oncontextmenu=event=>openCalendarMenu(event,job,b);
    b.onkeydown=event=>{if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10'))openCalendarMenu(event,job,b);};
    return b;
  }
  function renderWeek(board) {
    const monday=add(state.date,-((state.date.getDay()+6)%7)), dates=Array.from({length:5},(_,i)=>iso(add(monday,i)));
    $('calendar-range').textContent=`${label(dates[0])} – ${label(dates[4])}, ${monday.getFullYear()}`;
    const head=document.createElement('div');head.className='calendar-week-head';head.innerHTML='<span>Team</span><div class="calendar-days">'+dates.map(d=>`<span class="${d===iso(new Date())?'calendar-today-date ':''}${isClosedDate(d)?'calendar-blackout':''}" ${d===iso(new Date())?'aria-current="date"':''} ${isClosedDate(d)?'title="Shop closed"':''}>${day(d).toLocaleDateString(undefined,{weekday:'short'})}<strong>${day(d).getDate()}</strong></span>`).join('')+'</div>';board.append(head);
    [...teamRows(),{id:'finishing',name:'Final checks',color:'slate',people:0}].forEach(team=>{
      const row=document.createElement('div');row.className='calendar-week-row';row.innerHTML=`<div class="calendar-team calendar-color-${text(team.color)}"><strong>${text(team.name)}</strong><small>${team.people?team.people+' '+(team.people===1?'person':'people'):'Shared group'}</small></div><div class="calendar-lane"></div>`;
      const lane=row.lastElementChild;
      if(dates.includes(iso(new Date()))){const marker=document.createElement('div');marker.className='calendar-today-column';marker.style.left=(dates.indexOf(iso(new Date()))*20)+'%';lane.append(marker);}
      dates.forEach((date,index)=>{if(isClosedDate(date)){const marker=document.createElement('div');marker.className='calendar-blackout-column';marker.style.left=(index*20)+'%';marker.title='Shop closed';lane.append(marker);}});
      if(canEdit()&&team.id!=='finishing'){
        const targets=document.createElement('div');targets.className='calendar-slot-targets';
        dates.forEach(date=>{const b=document.createElement('button');b.type='button';b.className='calendar-slot-target';b.textContent=isClosedDate(date)?'Closed':'+';b.disabled=isClosedDate(date);b.setAttribute('aria-label',isClosedDate(date)?`${label(date)} is a shop closure`:`Schedule selected vehicle on ${team.name}, ${label(date)}`);
          b.onclick=()=>{if(state.selected)openJob(state.selected,{team:team.id,date});else message('Choose a vehicle in the acceptance queue, then choose its team and date.');};
          dropTarget(b,team.id,date);targets.append(b);});lane.append(targets);
      }
      const packed=bookingRows(visibleJobs().filter(j=>team.id==='finishing'||(j.team_ids||[j.team_id]).includes(team.id)).map(j=>({job:team.id==='finishing'?{...j,color:'slate',hours:state.data.settings.finishing_hours,kind:'checks'}:j,segments:team.id==='finishing'?j.finish_segments:j.segments})),dates);
      packed.rows.forEach(entry=>booking(entry.job,entry.segments,dates,lane).style.setProperty('--calendar-top',`${44+entry.row*70}px`));
      lane.style.minHeight=`${Math.max(126,56+packed.count*70)}px`;board.append(row);
    });
  }
  function renderMonth(board) {
    const month=new Date(state.date.getFullYear(),state.date.getMonth(),1,12),start=add(month,-month.getDay());
    $('calendar-range').textContent=month.toLocaleDateString(undefined,{month:'long',year:'numeric'});
    const head=document.createElement('div');head.className='calendar-month-head';head.innerHTML=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<span>${d}</span>`).join('');board.append(head);
    const weeks=Math.ceil((month.getDay()+new Date(month.getFullYear(),month.getMonth()+1,0).getDate())/7);
    const monthDates=Array.from({length:weeks*7},(_,i)=>iso(add(start,i)));
    let laneCount=0;
    const monthRows=teamRows().flatMap(team=>{
      const packed=bookingRows(visibleJobs().filter(j=>j.team_id===team.id).map(job=>({job,segments:job.segments})),monthDates);
      const rows=packed.rows.map(entry=>({...entry,row:entry.row+laneCount}));laneCount+=packed.count;return rows;
    });
    for(let w=0;w<weeks;w++){
      const dates=Array.from({length:7},(_,i)=>iso(add(start,w*7+i))),row=document.createElement('div');row.className='calendar-month-week';
      row.innerHTML='<div class="calendar-month-days">'+dates.map((d,i)=>`<span class="${d===iso(new Date())?'calendar-today-date ':''}${i===0||i===6?'calendar-weekend ':''}${isClosedDate(d)?'calendar-blackout ':''}${day(d).getMonth()!==month.getMonth()?'calendar-other-month':''}" ${isClosedDate(d)?'title="Shop closed"':''}>${day(d).getDate()}</span>`).join('')+'</div>';
      row.querySelectorAll('.calendar-month-days>span').forEach((cell,i)=>{if(dates[i]===iso(new Date()))cell.setAttribute('aria-current','date');if(canEdit()&&!isClosedDate(dates[i]))dropTarget(cell,state.teamFilter,dates[i]);});
      monthRows.forEach(entry=>{const b=booking(entry.job,entry.segments,dates,row);if(b){b.classList.add('calendar-month-booking');b.style.setProperty('--calendar-top',`${28+entry.row*28}px`);}});
      row.style.minHeight=`${Math.max(124,38+laneCount*28)}px`;board.append(row);
    }
  }
  function projectRows(project){
    const seen=new Set();
    return [...state.data.plan.jobs,...state.data.plan.queue,...state.data.plan.needs_review].filter(j=>{
      if(j.project_id!==project||seen.has(j.id))return false;seen.add(j.id);return true;
    });
  }
  async function removeBooking(project,unit=null){
    const rows=state.data.plan.jobs.filter(j=>(unit?j.id===unit:j.project_id===project)&&!j.historical&&j.shop_status!=='complete');
    const ids=new Set(rows.map(j=>j.id));
    const later=state.data.plan.jobs.some(j=>!ids.has(j.id)&&!j.historical&&j.shop_status!=='complete'&&rows.some(r=>r.team_ids.some(t=>j.team_ids.includes(t))&&j.start>=r.start));
    const choice=await askCalendar('Remove from schedule?',`Remove ${rows.length} booking${rows.length===1?'':'s'}?${later?' Shift the remaining builds back to fill the gap, or leave an open space?':' The units will return to the unscheduled list.'}`,later?'Shift builds back':'Remove booking',later?'Leave open space':'');
    if(!choice)return;
    await saveSchedule(null,{...(unit?{remove_vehicle:unit}:{remove_project:project}),fill_gap:later&&choice===true,reason:later&&choice===true?'Removed booking and filled the gap':'Removed booking; left open space'});
  }
  async function saveProjectAction(project,action){
    const related=[project];
    if(action.mode==='next_ready'){
      const source=state.data.plan.jobs.find(j=>j.id===action.id);
      for(const candidate of source?.recovery_candidates||[]){const job=state.data.plan.jobs.find(j=>j.id===candidate.id);if(job)related.push(job.project_id);}
    }
    const split=related.some(id=>state.data.split_projects?.includes(id));
    if(split&&!await askCalendar('Place all project units together?', 'These builds are not currently scheduled together. Rescheduling the whole project will place all its active accepted units together. Reschedule each unit individually if you want to keep their separate placements.', 'Place units together'))return;
    await saveSchedule(null,{schedule_action:{...action,whole_project:true,confirm_consolidation:split},reason:action.mode==='next_ready'?'Swapped project with next ready build':'Rescheduled whole project together'});
  }
  function openDropDialog(job,action){
    ++state.choiceRequest;state.selected=job.id;state.refreshDetail=null;
    const target=state.data.plan.jobs.find(j=>j.id===action.target_id),detail=$('calendar-detail');
    const count=projectRows(job.project_id).filter(j=>!j.historical&&j.shop_status!=='complete'&&j.acceptance_confirmed).length;
    const split=[job.project_id,target?.project_id].some(id=>id&&state.data.split_projects?.includes(id));
    detail.innerHTML=`<div class="calendar-detail-heading"><div><small>Move scheduled work</small><h3 id="calendar-detail-title">${text(job.agency_name||job.title)}</h3></div>${btn('×','calendar-detail-close')}</div>
      <form id="calendar-drop-form" class="calendar-fields"><label>Move<select id="calendar-drop-scope"><option value="project">Whole project · ${count} units</option><option value="unit">Selected unit only · ${text(vehicleName(job))}</option></select></label>
      ${target?`<p>${text({swap:'Swap with',before:'Insert before',after:'Insert after'}[action.mode])} ${text(target.agency_name||target.title)}.</p>`:`<label>Assigned team<select id="calendar-drop-team">${state.data.settings.teams.filter(t=>t.active).map(t=>`<option value="${text(t.id)}" ${t.id===(action.team_id||job.team_id)?'selected':''}>${text(t.name)}</option>`).join('')}</select></label><label>Scheduled start<input id="calendar-drop-date" type="date" required value="${text(action.start_date||job.start.slice(0,10))}"></label>`}
      <p id="calendar-drop-note" class="calendar-help"></p><div id="calendar-drop-impact" class="calendar-drop-impact" aria-live="polite"></div><div id="calendar-job-error" role="status"></div>${btn('Refresh dates','calendar-drop-refresh')}<button id="calendar-drop-save" type="submit" class="btn btn-primary" disabled>Confirm move</button></form>`;
    $('calendar-detail-close').onclick=()=>closeBubble('detail');
    const form=$('calendar-drop-form');
    const readAction=()=>{
      const whole=$('calendar-drop-scope').value==='project';
      return {...action,...(!target?{team_id:$('calendar-drop-team').value,start_date:$('calendar-drop-date').value}:{}),whole_project:whole,confirm_consolidation:whole&&split};
    };
    let pending=0,reviewedAction=null;
    const preview=async()=>{
      const sequence=++pending,move=readAction();reviewedAction=null;$('calendar-drop-save').disabled=true;$('calendar-job-error').textContent='';
      $('calendar-drop-note').textContent=move.whole_project?(split?'These builds are split. Confirming places all active accepted units together. Choose selected unit only to keep the other units in place.':`Moves all ${count} active accepted units together.`)+(target&&action.mode==='swap'?' The other project moves together too.':''):'Moves only the selected unit. Later bookings may shift to make room.';
      $('calendar-drop-impact').textContent='Calculating dates…';
      try{
        const body={...bodyFor(null),schedule_action:move,reason:'Moved scheduled work by drag'};
        const result=await request('/api/calendar/preview',body);
        if(sequence!==pending||!form.isConnected||detail.hidden)return;
        $('calendar-drop-impact').innerHTML=result.changes.map(change=>`<div><strong>${text(change.title)}</strong><span>${change.after?'Start '+dateTime(change.after.start)+' → Ready '+dateTime(change.after.ready):'Unscheduled'}</span></div>`).join('');
        if(result.conflicts.length)throw new Error(result.conflicts.join(' · '));
        reviewedAction={body,preview:result};$('calendar-drop-save').disabled=false;
      }catch(error){if(sequence===pending&&form.isConnected&&!detail.hidden)$('calendar-job-error').textContent=error.message;}
    };
    ['calendar-drop-scope','calendar-drop-team','calendar-drop-date'].forEach(id=>$(id)?.addEventListener('change',preview));
    $('calendar-drop-refresh').onclick=preview;
    form.onsubmit=async event=>{event.preventDefault();if(!reviewedAction)return;await saveSchedule(null,{},reviewedAction);};
    showBubble('detail');preview();
  }
  function openProject(project){
    ++state.choiceRequest;state.selected=null;state.refreshDetail=null;state.availability=null;
    const rows=projectRows(project),active=rows.filter(j=>!j.historical&&j.shop_status!=='complete'&&j.acceptance_confirmed);
    if(!rows.length)return;
    const scheduled=active.filter(j=>j.start).sort((a,b)=>a.start.localeCompare(b.start));
    const first=scheduled[0]||active[0],team=first?.team_id||state.data.settings.teams.find(t=>t.active)?.id;
    const detail=$('calendar-detail');
    detail.innerHTML=`<div class="calendar-detail-heading"><div><small>Whole project · ${rows.length} units</small><h3 id="calendar-detail-title">${text(rows[0].agency_name||rows[0].title)}</h3><span class="project-type-badge">${text(projectTypeLabel(rows[0]))}</span></div>${btn('×','calendar-detail-close')}</div>
      <div class="calendar-project-unit-list">${rows.map(j=>`<button type="button" class="calendar-project-unit btn btn-secondary" data-project-unit="${text(j.id)}"><strong>${text(vehicleName(j))}</strong><span>${j.start?text(j.team_name)+' · '+dateTime(j.start)+' → '+dateTime(j.end):text(j.reason||'Unscheduled')}</span>${statusBadges(j)}</button>`).join('')}</div>
      ${canEdit()&&first?`<form id="calendar-project-form" class="calendar-fields"><label>Assigned team<select id="calendar-project-team">${state.data.settings.teams.filter(t=>t.active).map(t=>`<option value="${text(t.id)}" ${t.id===team?'selected':''}>${text(t.name)}</option>`).join('')}</select></label><label>Scheduled start<input type="date" id="calendar-project-start" required value="${text(first.start?.slice(0,10)||iso(new Date()))}"></label><p class="calendar-help">Schedules all ${active.length} active accepted units together. Open a unit above to reschedule it individually.</p><button type="submit" class="btn btn-primary">${scheduled.length?'Reschedule':'Schedule'} project</button></form>`:''}
      <div id="calendar-job-error" role="status"></div>
      ${canEdit()&&scheduled.length?btn('Swap with next ready build','calendar-project-swap')+btn('Remove project from schedule','calendar-project-remove'):''}`;
    detail.querySelectorAll('[data-project-unit]').forEach(button=>button.onclick=()=>openJob(button.dataset.projectUnit));
    $('calendar-detail-close').onclick=()=>closeBubble('detail');
    $('calendar-project-form')?.addEventListener('submit',async event=>{event.preventDefault();await saveProjectAction(project,{id:first.id,mode:'new',team_id:$('calendar-project-team').value,start_date:$('calendar-project-start').value});});
    $('calendar-project-remove')?.addEventListener('click',()=>removeBooking(project));
    const swap=$('calendar-project-swap');if(swap){swap.disabled=!scheduled[0].recovery_candidates?.length;swap.title=swap.disabled?'No later ready build is scheduled on this team':'';swap.onclick=()=>saveProjectAction(project,{id:scheduled[0].id,mode:'next_ready'});}
    showBubble('detail');
  }
  function openJob(id,placement=null) {
    state.selected=id;state.choices=[];state.overlapApproval=null;++state.choiceRequest;
    state.bookingRevision=state.data.revision;state.bookingData=state.data;state.availability=null;
    const data=state.data,j=data.plan.jobs.find(j=>j.id===id)||data.plan.queue.find(j=>j.id===id),missing=data.plan.needs_review.find(j=>j.id===id),s=data.saved_jobs[id]||{};
    const custom=!j&&!missing,team=placement?.team||j?.team_id||data.settings.teams.find(t=>t.active)?.id;
    const detail=$('calendar-detail'),title=j&&!j.custom?vehicleName(j):j?.title||missing?.title||'Add job';
    const editable=canEdit()&&!j?.historical&&j?.shop_status!=='complete';
    detail.innerHTML=`<div class="calendar-detail-heading"><div>${j&&!j.custom?`<small>${text(j.agency_name)}</small>`:''}<h3 id="calendar-detail-title">${text(title)}</h3></div>${btn('×','calendar-detail-close')}</div>
    ${j&&!j.custom?`<div class="calendar-vehicle-identity">${statusBadges(j)}</div>`:''}
    ${j&&!j.custom?btn('View whole project','calendar-view-project'):''}
    <form id="calendar-job-form" ${editable?'':'hidden'}><fieldset ${editable?'':'disabled'} class="calendar-fields">
    ${custom||j?.custom?`<label>Job name<input id="calendar-job-title" maxlength="150" required value="${text(j?.title||'')}"></label>`:''}
    <label>Assigned team<select id="calendar-job-team">${data.settings.teams.filter(t=>t.active||t.id===team).map(t=>`<option value="${text(t.id)}" ${t.id===team?'selected':''}>${text(t.name)}${!t.active?' (retired)':''}</option>`).join('')}</select></label>
    ${j?.agency_team_history?.length?`<div class="calendar-team-history"><strong>Completed ${text(j.agency_name)} builds</strong>${j.agency_team_history.map(row=>`<span>${text(row.team_name)} · ${row.completed_builds}</span>${row.team_id!==team&&data.settings.teams.some(t=>t.id===row.team_id&&t.active)?`<button type="button" class="btn btn-secondary btn-sm" data-calendar-history-team="${text(row.team_id)}">Use this team</button>`:''}`).join('')}</div>`:''}
    <label>Scheduled start<input id="calendar-job-start" type="date" value="${text(placement?.date||s.start_date||j?.start?.slice(0,10)||missing?.original_start||'')}"><small>Leave blank for the nearest opening</small></label>
    <div class="calendar-ready" id="calendar-job-ready" role="status">${j?.ready&&!placement?`Build completes · ${dateTime(j.end)} · Ready for delivery · ${dateTime(j.ready)}`:'Calculating booking dates…'}</div>
    ${j&&!j.custom&&!j.saved?`<label class="calendar-checkbox calendar-project-checkbox"><input id="calendar-include-project" type="checkbox" ${placement?.includeProject?'checked':''}>Schedule the rest of this project</label>`:''}
    ${j?.project_type==='offsite'?`<p class="calendar-help">${text(j.service_details?.location||'')} · ${text(j.service_details?.contact||'')} · Travel: ${j.service_details?.travel_hours||0} labor hours</p>`:''}
    <div id="calendar-booking-overview" class="calendar-booking-overview"></div>
    <details class="calendar-advanced" ${custom||j?.custom||['service','offsite'].includes(j?.project_type)?'open':''}><summary>Advanced</summary><div class="calendar-fields">
    <label>Job type<select id="calendar-job-kind">${Object.entries(kinds).filter(([k])=>k!=='checks'&&(!['service','offsite'].includes(j?.project_type)||k===j.project_type)).map(([k,v])=>`<option value="${k}" ${k===(j?.kind||s.kind||(custom?'service':'strip_build'))?'selected':''}>${v}</option>`).join('')}</select></label>
    <label>Estimated labor hours${["service","offsite"].includes(j?.project_type)?" per vehicle":""}<input id="calendar-job-hours" type="number" min="0.25" max="4000" step="any" placeholder="Team default" value="${text(s.hours_manual||['service','offsite'].includes(j?.kind||s.kind)?s.hours||j?.hours||'':'')}"></label>
    </div>${j?.vin?`<p class="calendar-help">VIN ${text(j.vin)}</p>`:''}
    ${editable&&!custom&&!j?.custom&&_operationsCanEditAcceptanceDate()?btn('Edit acceptance date','calendar-job-accepted-edit'):''}
    ${editable&&j&&!j.custom&&canEdit()?btn('Edit delivery deadline','calendar-job-deadline'):''}
    </details></fieldset></form>
    ${!editable&&j&&!j.custom&&(_operationsCanEditAcceptanceDate()||canEdit())?`<details class="calendar-advanced"><summary>Advanced</summary>${_operationsCanEditAcceptanceDate()?btn('Edit acceptance date','calendar-job-accepted-edit'):''}${canEdit()?btn('Edit delivery deadline','calendar-job-deadline'):''}</details>`:''}
    <div id="calendar-job-error" class="calendar-job-notes" role="status"></div>
    ${!editable&&j?`<div class="calendar-job-summary"><span>Assigned team<strong>${text(j.team_name||'Unassigned')}</strong></span><span>Scheduled<strong>${label(j.start)} – ${label(j.ready)}</strong></span></div>`:''}
    ${j&&!j.custom?`<div class="calendar-job-summary" id="calendar-live-summary"><span>Accepted<strong>${label(j.accepted_date)}</strong></span><span>Deadline<strong>${j.deadline?label(j.deadline):'Not set'}</strong></span></div>`:''}
    <div class="calendar-job-notes" id="calendar-live-notes">${bookingWarnings(j).map(x=>`<span>${text(x)}</span>`).join('')}</div>
    ${editable&&j?.start?btn('Swap with next ready build','calendar-unit-swap')+btn('Remove unit from schedule','calendar-unit-remove'):''}`;
    const footer=document.createElement('div');footer.className='calendar-detail-footer';detail.append(footer);
    if(editable&&j?.recovery_candidates?.length){
      const recovery=document.createElement('section');recovery.className='calendar-recovery';
      recovery.innerHTML='<strong>Later ready-to-build projects on this team</strong>';
      j.recovery_candidates.forEach(candidate=>{const row=document.createElement('div'),button=document.createElement('button');
        row.textContent=`${candidate.agency_name} · ${candidate.title} · Accepted ${label(candidate.accepted_date)} · Scheduled ${dateTime(candidate.start)} `;
        button.type='button';button.className='btn btn-secondary btn-sm';button.textContent='Swap with this build';
        button.onclick=()=>saveSchedule(null,{schedule_action:{id,target_id:candidate.id,mode:'swap'},reason:'Swap blocked build with ready build'});
        row.append(button);recovery.append(row);});footer.prepend(recovery);
    }
    const history=(data.history||[]).filter(h=>h.changes.some(c=>c.id===id));
    const section=document.createElement('details');section.className='calendar-history';section.innerHTML='<summary>Booking change history</summary><div class="calendar-history-entries">'+(history.slice().reverse().map(h=>`<div class="calendar-history-entry"><strong>${text(h.actor)} · ${text(h.at.slice(0,16).replace('T',' '))}</strong><p>${text(h.reason)}</p>${h.changes.filter(c=>c.id===id).map(c=>`<p>${c.before?label(c.before.start)+' → '+label(c.before.ready):'Unscheduled'} → ${c.after?label(c.after.start)+' → '+label(c.after.ready):'Removed'}</p>`).join('')}</div>`).join('')||'<p>No booking changes yet.</p>')+'</div>';footer.append(section);
    if(editable)footer.insertAdjacentHTML('beforeend','<button id="calendar-confirm-booking" form="calendar-job-form" class="btn btn-primary btn-sm" type="submit">Confirm booking</button>');
    $('calendar-job-accepted-edit')?.addEventListener('click',()=>{closeBubble('detail');openAcceptanceDateEditor(id);});
    $('calendar-view-project')?.addEventListener('click',()=>openProject(j.project_id));
    $('calendar-unit-remove')?.addEventListener('click',()=>removeBooking(j.project_id,id));
    const swap=$('calendar-unit-swap');if(swap){swap.disabled=!j.recovery_candidates?.length;swap.title=swap.disabled?'No later ready build is scheduled on this team':'';swap.onclick=()=>saveSchedule(null,{schedule_action:{id,mode:'next_ready'},reason:'Swapped unit with next ready build'});}
    $('calendar-detail-close').onclick=()=>closeBubble('detail');
    let manualHours=Boolean(s.hours_manual||(['service','offsite'].includes(j?.kind||s.kind)&&s.hours)),availabilityTimer,previousTeam=team;
    const readEdit=()=>{
      const edit={id,team_id:$('calendar-job-team').value,kind:$('calendar-job-kind').value,
        hours:$('calendar-job-hours').value?Number($('calendar-job-hours').value):null,start_date:$('calendar-job-start').value,
        pinned:true,hours_manual:manualHours,team_ids:[$('calendar-job-team').value],team_assignment_manual:true};
      if($('calendar-job-title'))edit.title=$('calendar-job-title').value;
      return edit;
    };
    const includeProject=()=>Boolean($('calendar-include-project')?.checked);
    let savedDetails=s,initialEdit=readEdit();
    async function updateAvailability(autoTeam=false){
      const seq=++state.choiceRequest,edit=readEdit();
      if(!editable||((custom||j?.custom)&&!edit.title))return;
      if(['service','offsite'].includes(edit.kind)&&!edit.hours){$('calendar-job-ready').textContent='Enter labor hours in Advanced to calculate dates';return;}
      try{
        const result=await request('/api/calendar/preview',{availability:edit,include_project:includeProject()});
        if(seq!==state.choiceRequest||state.selected!==id||$('calendar-detail').hidden)return;
        state.choices=result.choices;
        if(autoTeam){const preferred=result.choices.find(c=>c.team_id===$('calendar-job-team').value);const free=preferred&&!preferred.busy&&!preferred.blocking_conflicts.length?preferred:result.choices.find(c=>!c.busy&&!c.blocking_conflicts.length);if(free)$('calendar-job-team').value=free.team_id;previousTeam=$('calendar-job-team').value;}
        state.availability={source:result.source_revision,key:bookingInputKey(readEdit(),includeProject()),choices:result.choices};
        for(const option of $('calendar-job-team').options){const choice=result.choices.find(c=>c.team_id===option.value),name=state.data.settings.teams.find(t=>t.id===option.value)?.name||option.value;option.textContent=(choice?.busy?'🔴 ':'')+name+(choice?.busy?' — Busy':'');option.style.color=choice?.busy?'#a52727':'';}
        const selected=result.choices.find(c=>c.team_id===$('calendar-job-team').value);
        if(selected){$('calendar-job-ready').textContent=`Build completes · ${dateTime(selected.end)} · Ready for delivery · ${dateTime(selected.ready)}`;renderBookingOverview(selected.vehicles);$('calendar-job-error').textContent=selected.blocking_conflicts.join(' · ');}
      }catch(e){if(seq===state.choiceRequest&&!$('calendar-detail').hidden){$('calendar-job-ready').textContent='Choose booking details to calculate dates';$('calendar-job-error').textContent=e.message;}}
    }
    function changed(){state.overlapApproval=null;++state.choiceRequest;clearTimeout(availabilityTimer);$('calendar-job-ready').textContent='Calculating booking dates…';availabilityTimer=setTimeout(()=>updateAvailability(),200);}
    detail.querySelectorAll('[data-calendar-history-team]').forEach(button=>button.onclick=()=>{const teamId=button.dataset.calendarHistoryTeam;if($('calendar-job-team').value!==teamId){$('calendar-job-team').value=teamId;changed();}});
    $('calendar-job-hours').oninput=()=>{manualHours=Boolean($('calendar-job-hours').value);changed();};
    $('calendar-job-start').oninput=changed;
    $('calendar-job-title')?.addEventListener('input',changed);
    $('calendar-include-project')?.addEventListener('change',changed);
    $('calendar-job-team').onchange=async()=>{
      state.overlapApproval=null;if(!manualHours)$('calendar-job-hours').value='';await updateAvailability();
      if($('calendar-detail').hidden)return;
      const choice=state.choices.find(c=>c.team_id===$('calendar-job-team').value);
      if(choice?.busy)$('calendar-job-error').textContent='This team has conflicting work. Choose a free date or drag to a booking edge to insert and review the later changes.';
      previousTeam=$('calendar-job-team').value;
    };
    $('calendar-job-kind').onchange=()=>{if(!manualHours)$('calendar-job-hours').value='';changed();};
    $('calendar-job-deadline')?.addEventListener('click',async()=>{
      closeBubble('detail');await initOperationsTab();const vehicle=_OPERATIONS.payload?.vehicles?.find(v=>v.vehicle_id===id);
      if(vehicle)_operationsOpenScheduleEditor([vehicle],j.title);else toast('Refresh Operations to edit this deadline','error');
    });
    $('calendar-job-form').onsubmit=async event=>{event.preventDefault();clearTimeout(availabilityTimer);await confirmBooking(readEdit(),{include_project:includeProject()});};
    state.refreshDetail=()=>{
      if(state.selected!==id||detail.hidden||state.busy)return;
      const latest=state.data.plan.jobs.find(row=>row.id===id)||state.data.plan.queue.find(row=>row.id===id)||state.data.plan.needs_review.find(row=>row.id===id);
      if(latest){
        const saved=state.data.saved_jobs[id]||{},entered=readEdit();
        if(JSON.stringify(saved)!==JSON.stringify(savedDetails)){
          // Refresh untouched fields; retain the scheduler's edits field by field.
          const values={team_id:saved.team_id||latest.team_id||entered.team_id,kind:saved.kind||latest.kind||entered.kind,
            start_date:saved.start_date||latest.start?.slice(0,10)||'',
            hours:saved.hours_manual||['service','offsite'].includes(saved.kind)?saved.hours||null:null,
            title:saved.title||latest.title};
          const controls={team_id:'team',kind:'kind',start_date:'start',hours:'hours',title:'title'};
          for(const [key,control] of Object.entries(controls)){
            const input=$('calendar-job-'+control);
            if(input&&entered[key]===initialEdit[key]){input.value=values[key]??'';initialEdit[key]=values[key];if(key==='hours')manualHours=Boolean(saved.hours_manual);}
          }
          savedDetails=saved;state.overlapApproval=null;
        }
        const identity=detail.querySelector('.calendar-vehicle-identity');if(identity)identity.innerHTML=statusBadges(latest);
        if($('calendar-live-summary'))$('calendar-live-summary').innerHTML=`<span>Accepted<strong>${label(latest.accepted_date)}</strong></span><span>Deadline<strong>${latest.deadline?label(latest.deadline):'Not set'}</strong></span>`;
        $('calendar-live-notes').innerHTML=bookingWarnings(latest).map(x=>`<span>${text(x)}</span>`).join('');
      }
      const confirm=$('calendar-confirm-booking');if(confirm)confirm.disabled=!latest||latest.historical||latest.shop_status==='complete'||!canEdit();
      if($('calendar-unit-swap'))$('calendar-unit-swap').disabled=!latest?.recovery_candidates?.length;
      clearTimeout(availabilityTimer);updateAvailability();
    };
    showBubble('detail');if(editable)updateAvailability(Boolean(placement?.autoTeam));
  }
  function renderBookingOverview(vehicles){
    $('calendar-booking-overview').innerHTML=vehicles.length>1?`<strong>${vehicles.length} vehicles in this booking</strong>`+vehicles.map(j=>`<div><span>${text(vehicleName(j))}</span><span>${label(j.start)} – ${label(j.ready)}</span></div>`).join(''):'';
  }
  const overlapKey=(overlaps,edit,include)=>JSON.stringify({overlaps:overlaps.map(j=>[j.id,j.start,j.end]).sort(),edit,include});
  const bookingInputKey=(edit,include)=>JSON.stringify({edit,include});
  const bookingDates=vehicles=>JSON.stringify(vehicles.map(j=>[j.id,j.start,j.ready]).sort());
  function bookingContext(data,id){
    const rows=[...data.plan.jobs,...data.plan.queue,...data.plan.needs_review],project=rows.find(j=>j.id===id)?.project_id||id;
    const ids=new Set([id,...rows.filter(j=>j.project_id===project).map(j=>j.id)]);
    return JSON.stringify({settings:data.settings,jobs:Object.entries(data.saved_jobs).filter(([key])=>ids.has(key)).sort()});
  }
  function confirmOverlap(overlaps){
    const names=[...new Set(overlaps.map(j=>j.agency_name||j.title))].join(', ');
    return askCalendar('This team is already busy',`This booking overlaps ${names}. Do you still want to add it to this team?`,'Allow overlapping booking');
  }
  async function confirmBooking(edit,extra={}){
    if(state.busy){$('calendar-job-error').textContent='Saving your previous local change…';return;}state.busy=true;
    ++state.choiceRequest;
    const submit=$('calendar-confirm-booking');if(submit)submit.disabled=true;
    try{
      $('calendar-job-error').textContent='Saving on this device…';
      // Operations revisions also change for notes, status refreshes and our own
      // date publication. Revalidate current data without discarding form edits.
      const current=await request('/api/calendar');
      const changed=bookingContext(current,state.selected)!==bookingContext(state.bookingData,state.selected);
      state.bookingData=current;state.bookingRevision=current.revision;state.data=current;render();
      if(changed){
        const saved=current.plan.jobs.find(j=>j.id===state.selected);
        throw new Error(`This booking was updated. ${saved?'Currently saved: '+saved.team_name+', '+dateTime(saved.start)+' → '+dateTime(saved.ready)+'. ':''}Your entries are preserved. Check them, then confirm again to apply your changes.`);
      }
      const include=Boolean(extra.include_project),shown=state.availability;
      let body={revision:current.revision,source_revision:current.source_revision,edit,reason:extra.remove_project?'Project removed from schedule':'Booking confirmed',...extra};
      let preview=await request('/api/calendar/preview',{...body,refresh_operations:true});
      body.source_revision=preview.source_revision;
      if(preview.conflicts.length)throw new Error(preview.conflicts.join(' · '));
      if(edit&&shown?.key===bookingInputKey(edit,include)&&shown.source!==preview.source_revision){
        const previous=shown.choices.find(c=>c.team_id===edit.team_id),vehicles=preview.plan.jobs.filter(j=>j.staged),selected=vehicles.find(j=>j.id===edit.id);
        if(previous&&selected&&bookingDates(previous.vehicles)!==bookingDates(vehicles)){
          $('calendar-job-ready').textContent=`Build completes · ${dateTime(selected.end)} · Ready for delivery · ${dateTime(selected.ready)}`;renderBookingOverview(vehicles);
          state.availability={source:preview.source_revision,key:shown.key,choices:[{team_id:edit.team_id,vehicles}]};state.overlapApproval=null;
          throw new Error('Operations updated this booking’s dates or included vehicles. Check the updated dates above, then confirm booking again.');
        }
      }
      state.edit=body;
      const queued=await request('/api/calendar/save-background',{...body,preview_token:preview.preview_token,request_id:crypto.randomUUID()});
      ++state.request;showSave(queued.save);state.data=queued;render();closeBubble('detail');pollSave();
    }catch(e){$('calendar-job-error').textContent=e.message;}
    finally{state.busy=false;if(submit)submit.disabled=false;}
  }
  const bodyFor = edit => ({revision:state.data.revision,source_revision:state.data.source_revision,edit});
  async function saveSchedule(edit=null,extra={},reviewed=null){
    if(state.busy)return;state.busy=true;
    try{
      const body=reviewed?.body||{...bodyFor(edit),reason:'Calendar change confirmed',...extra};
      const preview=reviewed?.preview||await request('/api/calendar/preview',body);
      if(preview.conflicts.length)throw new Error(preview.conflicts.join(' · '));
      state.edit=body;
      const queued=await request('/api/calendar/save-background',{...body,preview_token:preview.preview_token,request_id:crypto.randomUUID()});
      ++state.request;state.data=queued;showSave(queued.save);render();
      if(!$('calendar-detail').hidden)closeBubble('detail');
      if(extra.settings){settingsData=queued;if($('calendar-settings-message'))$('calendar-settings-message').textContent='Settings saved on this device.';}
      message('Schedule saved.');pollSave();
    }catch(e){
      message(e.message);
      if(!$('calendar-detail').hidden&&$('calendar-job-error'))$('calendar-job-error').textContent=e.message;
      if(extra.settings&&$('calendar-settings-message'))$('calendar-settings-message').textContent=e.message;
    }finally{state.busy=false;}
  }
  async function reviewSync(){
    if(state.busy)return;state.busy=true;message('Loading the shared changes for review…');
    try{
      const result=await request('/api/calendar/sync-review',{});state.syncReview=result;
      const format=value=>value?`${(value.team_ids||[]).map(id=>result.settings.teams.find(t=>t.id===id)?.name||id).join(' + ')} · ${dateTime(value.start)} → ${dateTime(value.ready)}`:'Unscheduled';
      const settingsText=s=>`${s.hours_per_day}-hour days · ${s.buffer_percent}% weekly capacity reserve · ${s.finishing_hours} hours for final checks · ${federalHolidayIds(s).length}/${federalHolidays.length} observed U.S. federal holidays selected. `+s.teams.map(t=>`${t.name}: ${t.people} people, ${t.build_hours} build labor hours/vehicle, ${t.strip_hours} strip labor hours/vehicle${t.active?'':' (retired)'}${t.days_off.length?', days off '+t.days_off.map(label).join(', '):''}`).join('; ')+(s.holidays.length?'. Additional shop closed: '+s.holidays.map(label).join(', '):'');
      $('calendar-review-title').textContent='Resolve shared schedule changes';
      $('calendar-review-body').innerHTML='<p>Your changes are saved on this device. Check the shared booking and your proposed booking before syncing.</p><div class="calendar-review-list">'+result.changes.map(c=>`<div><strong>${text(c.title)}</strong><span>Shared: ${text(format(c.before))}</span><span>Your booking: ${text(format(c.after))}</span></div>`).join('')+'</div>'+
        (result.settings_changed?`<p>Team settings will also change.</p><p>Shared: ${text(settingsText(result.settings_before))}</p><p>Your settings: ${text(settingsText(result.settings))}</p>`:'');
      $('calendar-review-reason').closest('label').hidden=true;$('calendar-review-message').textContent=result.blocking_conflicts.join(' · ');
      $('calendar-review-save').textContent='Apply reviewed changes';$('calendar-review-save').disabled=Boolean(result.blocking_conflicts.length);
      $('calendar-review-modal').hidden=false;$('calendar-review-modal').classList.add('open');$('calendar-review-close').focus();
    }catch(e){message(e.message);}finally{state.busy=false;}
  }
  function closeReview(){if(state.busy)return;$('calendar-review-modal').hidden=true;$('calendar-review-modal').classList.remove('open');if(!$('calendar-detail').hidden)$('calendar-detail').focus();}
  const saveBanner=document.createElement('div');saveBanner.id='calendar-save-status';saveBanner.className='calendar-save-status';saveBanner.hidden=true;saveBanner.setAttribute('role','status');
  $('tab-calendar').querySelector('.calendar-shell').prepend(saveBanner);
  function showSave(save){
    if(Number(save.id)<Number(state.saveId))return;
    state.saving=['saving','syncing'].includes(save.state);state.syncFailed=['failed','conflict','interrupted'].includes(save.state);state.syncConflict=save.state==='conflict';state.saveId=save.id;
    saveBanner.hidden=['idle','complete'].includes(save.state);
    saveBanner.textContent=save.message||'';
    if(save.state==='syncing')saveBanner.textContent+=' You can keep editing.';
    $('calendar-review').hidden=!canEdit()||(!state.syncFailed&&(state.saving||!state.data?.pending_date_count));
    $('calendar-review').textContent=state.syncConflict?'Review sync conflict':state.syncFailed?'Retry sync':'Retry date update';
    saveBanner.dataset.state=save.state;
  }
  async function pollSave(){
    if(state.polling||!appHasCapability('operations.view'))return;state.polling=true;
    try{const result=await request('/api/calendar/save-status'),wasSaving=state.saving;
      showSave(result.save);
      if(wasSaving&&!state.saving){
        if($('calendar-settings-message'))$('calendar-settings-message').textContent=result.save.state==='complete'?'Team settings saved.':result.save.message;
        if(state.edit?.settings){settingsData=await request('/api/calendar');if(!$('stab-calendar-teams').hidden){renderSettings();$('calendar-settings-message').textContent=result.save.state==='complete'?'Team settings saved.':result.save.message;}}
        if(!$('tab-calendar').hidden)await initCalendarTab();
        if(!$('tab-operations').hidden)await initOperationsTab();
      }
    }catch(e){if(state.saving)saveBanner.textContent='Checking save progress… Keep the app open.';}
    finally{state.polling=false;}
  }
  setInterval(pollSave,2000);
  $('calendar-review-save').onclick=async()=>{
    if(state.syncReview){
      if(state.busy)return;state.busy=true;$('calendar-review-save').disabled=true;
      try{
        const result=state.syncReview;
        if(result.overlaps.length&&!await confirmOverlap(result.overlaps))return;
        const saved=await request('/api/calendar/resolve-sync',{review_token:result.review_token,allow_overlap:Boolean(result.overlaps.length)});
        ++state.request;state.data=saved;showSave(saved.save);render();state.syncReview=null;state.busy=false;closeReview();
      }catch(e){$('calendar-review-message').textContent=e.message;}
      finally{state.busy=false;$('calendar-review-save').disabled=Boolean(state.syncReview?.blocking_conflicts.length);}
      return;
    }
  };
  ['calendar-review-close','calendar-review-cancel'].forEach(id=>$(id).onclick=closeReview);
  $('calendar-review').onclick=async()=>{if(state.syncConflict)return reviewSync();if(!state.syncFailed)return saveSchedule();try{const result=await request('/api/calendar/retry-sync',{});showSave(result.save);}catch(e){message(e.message);}};$('calendar-refresh').onclick=initCalendarTab;
  window.refreshCalendarDetails=id=>{if(state.selected===id)openJob(id);};
  $('calendar-team-filter').onchange=e=>{state.teamFilter=e.target.value;render();};
  $('calendar-today').onclick=()=>{state.date=new Date();render();};
  ['week','month'].forEach(v=>$('calendar-'+v).onclick=()=>{state.view=v;render();});
  ['prev','next'].forEach((v,i)=>$('calendar-'+v).onclick=()=>{state.date=state.view==='week'?add(state.date,i?7:-7):new Date(state.date.getFullYear(),state.date.getMonth()+(i?1:-1),1,12);render();});
  $('calendar-month-picker').onchange=e=>{if(e.target.value){state.date=day(e.target.value+'-01');render();}};
  window.openCalendarVehicle=async id=>{switchTab('calendar');await initCalendarTab();if(id){const j=state.data?.plan.jobs.find(x=>x.id===id);if(j)state.date=day(j.start);render();openJob(id);}};

  async function refreshCalendar(){
    if(document.hidden||$('tab-calendar').hidden||state.busy||state.autoRefreshing||drag||!$('calendar-review-modal').hidden||!$('calendar-choice-modal').hidden)return;
    state.autoRefreshing=true;try{await initCalendarTab(true);}finally{state.autoRefreshing=false;}
  }
  setInterval(refreshCalendar,15000);
  window.addEventListener('focus',refreshCalendar);
  document.addEventListener('visibilitychange',refreshCalendar);

  // Team management belongs in General Settings, with stable IDs across renames.
  let settingsData=null;
  window.initCalendarSettings=async()=>{
    const host=$('stab-calendar-teams');host.innerHTML='<div class="card">Loading teams…</div>';
    try {settingsData=await request('/api/calendar');renderSettings();}catch(e){host.textContent=e.message;}
  };
  function renderSettings(){
    const s=settingsData.settings;
    const selectedFederalHolidays=new Set(federalHolidayIds(s));
    const federalHolidayChoices=federalHolidays.map(([id,name])=>`<label class="calendar-checkbox"><input data-us-federal-holiday="${id}" type="checkbox" ${selectedFederalHolidays.has(id)?'checked':''}>${name}</label>`).join('');
    $('stab-calendar-teams').innerHTML=`<div class="card"><div class="calendar-toolbar"><h2>Teams & Calendar</h2>${btn('+ Add team','calendar-team-add')}${btn('Save settings','calendar-settings-save',true)}</div>
    <div id="calendar-settings-message" role="status"></div><div class="calendar-settings-grid" id="calendar-team-list"></div>
    <div class="calendar-fields calendar-shop-settings"><label>Hours per person per day<input id="calendar-workday" type="number" min="1" max="12" step="0.5" value="${s.hours_per_day}"></label><label>Weekly capacity reserve (%)<input id="calendar-shop-buffer" type="number" min="0" max="50" value="${s.buffer_percent}"></label><label>Final checks (hours)<input id="calendar-check-hours" type="number" min="0" max="40" step="0.5" value="${s.finishing_hours}"></label><fieldset class="calendar-holiday-toggles"><legend>Observed U.S. federal holidays</legend><div>${federalHolidayChoices}</div></fieldset><div class="calendar-date-list" id="calendar-holidays"></div></div><p class="calendar-help">Build and strip defaults are total labor hours per vehicle. The capacity reserve reduces schedulable weekly availability; it does not add hours to a build estimate. Select the observed federal holidays that close the shop, then add any other closed dates below. Team defaults apply to new jobs. Retiring a team keeps its past assignments.</p></div>`;
    s.teams.forEach(t=>{const row=document.createElement('fieldset');row.className='calendar-team-settings';row.dataset.teamId=t.id;
      row.innerHTML=`<legend>${text(t.name)}</legend><label>Team name<input data-field="name" maxlength="80" value="${text(t.name)}"></label><label>People<input data-field="people" type="number" min="1" max="12" value="${t.people}"></label><label>Build labor hours / vehicle<input data-field="build_hours" type="number" min="1" max="2000" value="${t.build_hours}"></label><label>Strip labor hours / vehicle<input data-field="strip_hours" type="number" min="0" max="2000" value="${t.strip_hours}"></label><label>Color<select data-field="color">${colors.map(c=>`<option ${c===t.color?'selected':''}>${c}</option>`).join('')}</select></label><label class="calendar-checkbox"><input data-field="active" type="checkbox" ${t.active?'checked':''}>Active team</label><div class="calendar-date-list" data-team-days></div>`;
      $('calendar-team-list').append(row);dateList(row.querySelector('[data-team-days]'),'Team days off',t.days_off);});
    dateList($('calendar-holidays'),'Additional shop closed dates',s.holidays);
    $('calendar-team-add').onclick=()=>{readSettings();s.teams.push({id:'team-'+crypto.randomUUID(),name:'New team',people:2,build_hours:60,strip_hours:6,color:colors[s.teams.length%colors.length],active:true,days_off:[]});renderSettings();};
    $('calendar-settings-save').onclick=async()=>{readSettings();state.data=settingsData;await saveSchedule(null,{settings:s,reason:'Team settings updated'});};

  }
  function dateList(host,name,initial){
    let dates=[...initial];
    function draw(){host.dataset.dates=JSON.stringify(dates);host.replaceChildren();const labelNode=document.createElement('label');labelNode.textContent=name;
      const controls=document.createElement('div');controls.className='calendar-date-add';const input=document.createElement('input');input.type='date';input.setAttribute('aria-label',name);labelNode.append(input);
      const addButton=document.createElement('button');addButton.type='button';addButton.className='btn btn-secondary btn-sm';addButton.textContent='Add';addButton.onclick=()=>{if(input.value&&!dates.includes(input.value)){dates.push(input.value);dates.sort();draw();}};controls.append(labelNode,addButton);host.append(controls);
      dates.forEach(value=>{const chip=document.createElement('button');chip.type='button';chip.className='calendar-date-chip';chip.textContent=label(value)+' ×';chip.setAttribute('aria-label','Remove '+label(value)+' from '+name);chip.onclick=()=>{dates=dates.filter(d=>d!==value);draw();};host.append(chip);});
    }draw();
  }
  function readSettings(){const s=settingsData.settings;document.querySelectorAll('.calendar-team-settings').forEach(row=>{const t=s.teams.find(t=>t.id===row.dataset.teamId);t.days_off=JSON.parse(row.querySelector('[data-team-days]').dataset.dates);row.querySelectorAll('[data-field]').forEach(input=>{const key=input.dataset.field;t[key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):key==='days_off'?input.value.split(/[\n,]+/).map(x=>x.trim()).filter(Boolean):input.value;});});s.hours_per_day=Number($('calendar-workday').value);s.buffer_percent=Number($('calendar-shop-buffer').value);s.finishing_hours=Number($('calendar-check-hours').value);s.us_federal_holidays=[...document.querySelectorAll('[data-us-federal-holiday]:checked')].map(input=>input.dataset.usFederalHoliday);delete s.use_us_federal_holidays;s.holidays=JSON.parse($('calendar-holidays').dataset.dates);}
})();
