// ═══════════════════════════════════════════════════════
// CANVAS UTILITIES (shared by placements + fixtures)
// ═══════════════════════════════════════════════════════
//
// Placement math (slot patterns: single/horizontal/vertical/mirror/vertical_mirror) is
// canonically defined in domain/geometry.py — slot_relative_positions().
// The JS below mirrors that logic for the canvas preview. If you change
// pattern semantics, spacing rules, or mirror offset behavior here, update
// domain/geometry.py to match — server-rendered PowerPoint and the client
// preview must agree.

// ── multi-dot positioning ────────────────────────────────────────
function getSlotPositions(loc, box){
  const [bl,bt,bw,bh]=box;
  const baseCx = bl + loc.x * bw;
  const baseCy = bt + loc.y * bh;
  const pattern = loc.pattern || "single";
  const slotCount = loc.slot_count || 1;

  if(slotCount<=1 || pattern==="single") return [[baseCx,baseCy]];

  // use saved h_spacing (or legacy spacing) if set, otherwise ~6% of image width per slot gap
  const rawSpacing = loc.h_spacing ?? loc.spacing;
  const spacing = (rawSpacing && rawSpacing > 0) ? bw * rawSpacing : bw * 0.06;

  if(pattern==="horizontal"){
    const totalW = spacing*(slotCount-1);
    const startX = baseCx - totalW/2;
    return Array.from({length:slotCount}, (_,i) => [startX+i*spacing, baseCy]);
  }

  if(pattern==="vertical"){
    const rawVSpacing=loc.v_spacing;
    const vSpacing=(rawVSpacing && rawVSpacing>0) ? bh*rawVSpacing : spacing;
    const totalH=vSpacing*(slotCount-1);
    const startY=baseCy-totalH/2;
    return Array.from({length:slotCount},(_,i)=>[baseCx,startY+i*vSpacing]);
  }

  if(pattern==="vertical_mirror"){
    const rawVSpacing=loc.v_spacing;
    const vSpacing=(rawVSpacing && rawVSpacing>0) ? bh*rawVSpacing : spacing;
    const centerY=bt+0.5*bh;
    let offsetY=Math.abs(baseCy-centerY);
    if(offsetY<0.001 && vSpacing) offsetY=vSpacing/2;
    if(slotCount===2) return [[baseCx,centerY-offsetY],[baseCx,centerY+offsetY]];
    const half=Math.floor(slotCount/2),positions=[];
    for(let i=0;i<half;i++){
      const off=offsetY+i*vSpacing;
      positions.push([baseCx,centerY-off]);
      positions.push([baseCx,centerY+off]);
    }
    return positions;
  }

  if(pattern==="mirror"){
    const centerX = bl + 0.5*bw;
    const offsetX = Math.abs(baseCx - centerX);
    if(slotCount===2) return [[centerX-offsetX,baseCy],[centerX+offsetX,baseCy]];
    const half=Math.floor(slotCount/2);
    const positions=[];
    for(let i=0;i<half;i++){
      const off=offsetX+i*spacing;
      positions.push([centerX-off,baseCy]);
      positions.push([centerX+off,baseCy]);
    }
    return positions;
  }

  return [[baseCx,baseCy]];
}
