import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { regions, get, finite, fmt, setText } from './telemetry.js';
import { advancePhase, heartbeatScale, inspiration, smoothStep, focusTargets, targetForMesh, fitDistance, visualStyle } from './body_dynamics.js';

function disposeTree(root) {
  const geometries=new Set(), materials=new Set(), textures=new Set();
  root.traverse(o=> {
    if(o.geometry) geometries.add(o.geometry);
    for(const m of Array.isArray(o.material)?o.material:[o.material]) if(m) {
      materials.add(m); for(const value of Object.values(m)) if(value?.isTexture) textures.add(value);
    }
  });
  textures.forEach(x=>x.dispose()); materials.forEach(x=>x.dispose()); geometries.forEach(x=>x.dispose());
}
export class AresBodyHUD {
  constructor(container) {
    this.container=container; this.meshes={}; this.statuses={}; this.outlines=[];
    this.heartPhase=0; this.breathPhase=0; this.freshAt=-Infinity; this.layerVisibility={brain:true,eyes:true};
    this.reduced=matchMedia('(prefers-reduced-motion: reduce)'); this.auto=!this.reduced.matches;
    this.abort=new AbortController(); const opts={signal:this.abort.signal};
    this.scene=new THREE.Scene(); this.camera=new THREE.PerspectiveCamera(34,1,.005,30);
    this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.6)); this.renderer.setClearColor(0,0);
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    const canvas=this.renderer.domElement;
    canvas.setAttribute('aria-label','Holographic anatomy. Drag to rotate, scroll or pinch to zoom. Organ buttons focus individual systems.');
    container.append(canvas); this.controls=new OrbitControls(this.camera,canvas);
    this.controls.enableDamping=true; this.controls.enablePan=false;
    this.controls.minPolarAngle=Math.PI*.27; this.controls.maxPolarAngle=Math.PI*.73;
    this.controls.rotateSpeed=.7; this.controls.zoomSpeed=.7; this.controls.autoRotateSpeed=.72;
    this.lastInteraction=performance.now();
    this.controls.addEventListener('start',()=> {
      this.lastInteraction=performance.now();this.interacting=true;
      this.cameraTransition=null;this.controls.enableDamping=true;
    });
    this.controls.addEventListener('end',()=>{this.lastInteraction=performance.now();this.interacting=false;});
    // Uniform neutral illumination on both sides. Former cyan/blue unequal keys
    // created an apparent left/right material split on this symmetric export.
    this.scene.add(new THREE.AmbientLight(0xd5edff,.8));
    this.scene.add(new THREE.HemisphereLight(0xdbefff,0x28405c,.6));
    for(const x of [-1,1]) {
      const light=new THREE.DirectionalLight(0xdbefff,.7);light.position.set(x,1.5,2.5);this.scene.add(light);
    }
    this.raycaster=new THREE.Raycaster();
    canvas.addEventListener('pointerdown',e=>{this.pointer={x:e.clientX,y:e.clientY,id:e.pointerId};},opts);
    canvas.addEventListener('pointerup',e=> {
      if(!this.pointer || this.pointer.id!==e.pointerId || Math.hypot(e.clientX-this.pointer.x,e.clientY-this.pointer.y)>5) return;
      this.pick(e.clientX,e.clientY);
    },opts);
    canvas.addEventListener('pointercancel',()=>{this.pointer=null;},opts);
    canvas.addEventListener('webglcontextlost',e=> {
      e.preventDefault();setText('model-status','3D context lost. Reload to restore the model.');document.getElementById('model-status').hidden=false;
    },opts);
    for(const [key,target] of Object.entries(focusTargets)) {
      const label=document.getElementById(target.pin).closest('.body-callout');
      label.setAttribute('role','button');label.tabIndex=0;label.setAttribute('aria-label',`Focus ${target.label}`);label.setAttribute('aria-pressed','false');
      label.addEventListener('click',()=>this.select(target.region,target.meshes[0]),opts);
      label.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();this.select(target.region,target.meshes[0]);}},opts);
    }
    for(const key of ['brain','eyes']) document.getElementById(`layer-${key}`).addEventListener('change',e=>this.setLayerVisibility(key,e.target.checked),opts);
    document.getElementById('reset-view').addEventListener('click',()=>this.reset(),opts);
    document.getElementById('auto-rotate').addEventListener('click',()=>{this.auto=!this.auto;this.syncAuto();},opts);
    this.reduced.addEventListener('change',()=>{this.auto=!this.reduced.matches;this.syncAuto();},opts);
    this.syncAuto();this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(container);
    this.load();this.animate(0);
  }
  syncAuto() {
    const button=document.getElementById('auto-rotate');
    button.setAttribute('aria-pressed',String(this.auto));button.disabled=!!this.selectedTarget;
    button.textContent=this.selectedTarget?'Orbit paused':'Auto rotate';
  }
  async load() {
    try {
      const gltf=await new GLTFLoader().loadAsync(new URL('../assets/models/ares_upper_body_hologram.glb',import.meta.url).href);
      if(this.disposed) {disposeTree(gltf.scene);return;}
      this.model=gltf.scene;this.outlines ||= [];const originals=new Set();
      this.model.traverse(mesh=> {
        if(!mesh.isMesh) return;
        const key=targetForMesh(mesh.name);
        if(!key) {mesh.visible=false;return;}
        this.meshes[mesh.name]=mesh;mesh.userData.region=focusTargets[key].region;mesh.userData.target=key;
        for(const m of Array.isArray(mesh.material)?mesh.material:[mesh.material]) originals.add(m);
        // One consistent holographic surface per mesh; eye vertex colors are
        // deliberately omitted so realistic white sclera/pupil contrast is subdued.
        const style=visualStyle(mesh.name,'cyan',false,false);
        mesh.material=new THREE.MeshPhongMaterial({color:style.color,emissive:style.color,emissiveIntensity:style.emissive,shininess:25,transparent:true,opacity:style.opacity,depthWrite:false,side:THREE.FrontSide});
        mesh.userData.baseOpacity=style.opacity;mesh.userData.baseScale=mesh.scale.clone();
        if(['HEART','LUNG_LEFT','LUNG_RIGHT'].includes(mesh.name)) {
          // Recenter only local geometry, compensating the node translation.
          // Animation changes size around each organ, never its anatomical position.
          mesh.geometry.computeBoundingBox();const c=mesh.geometry.boundingBox.getCenter(new THREE.Vector3());
          mesh.geometry.translate(-c.x,-c.y,-c.z);mesh.position.add(c.multiply(mesh.scale).applyQuaternion(mesh.quaternion));
        }
      });
      for(const m of originals) {for(const value of Object.values(m)) if(value?.isTexture)value.dispose();m.dispose();}
      const missing=Object.values(focusTargets).flatMap(t=>t.meshes).filter(n=>!this.meshes[n]);
      if(missing.length) throw new Error(`Missing exported meshes: ${missing.join(', ')}`);
      this.model.updateMatrixWorld(true);const bounds=new THREE.Box3().setFromObject(this.model);
      this.size=bounds.getSize(new THREE.Vector3());this.localCenter=bounds.getCenter(new THREE.Vector3());
      this.model.position.sub(this.localCenter);this.scene.add(this.model);
      for(const mesh of Object.values(this.meshes)) this.addOutline(mesh);
      this.createScanner();this.reset(false);document.getElementById('model-status').hidden=true;
      this.container.dataset.loaded='true';this.container.dataset.meshes=Object.keys(this.meshes).join(',');
      this.update(this.packet,this.statuses,false);
    } catch(error) {
      setText('model-status',`Anatomical model unavailable: ${error.message}`);document.getElementById('model-status').hidden=false;this.container.dataset.loaded='error';
    }
  }
  addOutline(mesh) {
    if(mesh.name.startsWith('OPTIC')) return;
    const skin=mesh.name==='BODY_SURFACE';
    const material=skin
      ?new THREE.MeshBasicMaterial({color:0x35c5eb,wireframe:true,transparent:true,opacity:.09,depthWrite:false})
      :new THREE.LineBasicMaterial({color:mesh.name==='BRAIN'?0xb39ee8:0x62c9ec,transparent:true,opacity:mesh.name.startsWith('EYE') ? .025 : .065,depthWrite:false});
    const outline=skin?new THREE.Mesh(mesh.geometry,material):new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry,32),material);
    outline.userData.baseOpacity=material.opacity;outline.raycast=()=>{};mesh.add(outline);this.outlines.push(outline);
  }
  createScanner() {
    this.scan=new THREE.Mesh(new THREE.PlaneGeometry(2,2),new THREE.ShaderMaterial({
      transparent:true,depthWrite:false,side:THREE.DoubleSide,uniforms:{tint:{value:new THREE.Color(0x55cbea)}},
      vertexShader:'varying vec2 p; void main(){p=uv*2.0-1.0;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader:`varying vec2 p; uniform vec3 tint;
        void main(){float radius=length(p);if(radius>1.0)discard;
          vec2 q=p*8.0;vec2 d=abs(fract(q-0.5)-0.5)/max(fwidth(q),vec2(0.0001));
          float grid=1.0-min(min(d.x,d.y),1.0);
          float rim=smoothstep(0.965,0.99,radius)*(1.0-smoothstep(0.99,1.0,radius));
          gl_FragColor=vec4(tint,0.009+grid*0.035+rim*0.085);}`
    }));
    this.scan.rotation.x=-Math.PI/2;this.scan.scale.set(this.size.x*.61,this.size.z*.72,1);
    this.scan.position.copy(this.localCenter);this.scan.raycast=()=>{};this.model.add(this.scan);
  }
  resize() {
    const width=this.container.clientWidth,height=this.container.clientHeight;if(!width||!height)return;
    this.camera.aspect=width/height;this.camera.updateProjectionMatrix();this.renderer.setSize(width,height);
    if(this.model) {if(this.selectedTarget)this.focusOn(this.selectedTarget,false);else this.frameOverview(false);}
  }
  transitionTo(position,target,animate=true) {
    this.controls.enableDamping=false;this.controls.update();
    if(!animate || this.reduced?.matches) {
      this.camera.position.copy(position);this.controls.target.copy(target);this.camera.lookAt(target);this.controls.update();this.controls.enableDamping=true;this.cameraTransition=null;return;
    }
    this.cameraTransition={fromPosition:this.camera.position.clone(),fromTarget:this.controls.target.clone(),position:position.clone(),target:target.clone(),start:performance.now(),duration:900};
  }
  stepCamera(now) {
    const tr=this.cameraTransition;if(!tr)return false;
    const elapsed=(now-tr.start)/tr.duration,t=smoothStep(elapsed);
    this.camera.position.lerpVectors(tr.fromPosition,tr.position,t);this.controls.target.lerpVectors(tr.fromTarget,tr.target,t);this.camera.lookAt(this.controls.target);
    if(elapsed>=1){this.cameraTransition=null;this.controls.enableDamping=true;this.controls.update();}
    return true;
  }
  frameOverview(animate=true) {
    if(!this.size)return;
    this.distance=fitDistance(this.size,this.camera.aspect,this.camera.fov,1.045);
    // Slightly lower target brings the lower cut edge close to the bottom panel.
    const target=new THREE.Vector3(0,-this.size.y*.012,0);
    this.controls.minDistance=this.distance*.52;this.controls.maxDistance=this.distance*1.9;
    this.transitionTo(target.clone().add(new THREE.Vector3(0,this.size.y*.22,this.distance)),target,animate);
  }
  focusOn(key,animate=true) {
    if(!focusTargets[key] || !this.model)return;
    this.model.updateMatrixWorld(true);const bounds=new THREE.Box3();
    for(const name of focusTargets[key].meshes) if(this.meshes[name])bounds.expandByObject(this.meshes[name]);
    const size=bounds.getSize(new THREE.Vector3()),target=bounds.getCenter(new THREE.Vector3());
    const distance=fitDistance(size,this.camera.aspect,this.camera.fov,1.5);
    const direction=this.camera.position.clone().sub(this.controls.target).normalize();if(direction.lengthSq()===0)direction.set(0,0,1);
    this.controls.minDistance=Math.max(.035,distance*.6);this.controls.maxDistance=Math.max(this.distance*1.9,distance*2);
    this.transitionTo(target.clone().addScaledVector(direction,distance),target,animate);
  }
  reset(animate=true) {
    this.selectedTarget=null;this.selected=null;this.selectedMesh=null;this.layerVisibility={brain:true,eyes:true};
    for(const key of ['brain','eyes']) {const checkbox=document.getElementById(`layer-${key}`);if(checkbox)checkbox.checked=true;}
    for(const mesh of Object.values(this.meshes))mesh.visible=true;
    this.syncSelection();this.frameOverview(animate);this.lastInteraction=performance.now();this.syncAuto();
    setText('selected-region','Overview · select an organ to inspect its telemetry.');
  }
  setLayerVisibility(key,visible) {
    if(!['brain','eyes'].includes(key))return;
    this.layerVisibility[key]=visible;for(const name of focusTargets[key].meshes)if(this.meshes[name])this.meshes[name].visible=visible;
    if(!visible && this.selectedTarget===key){this.selectedTarget=null;this.selected=null;this.syncSelection();this.frameOverview();this.syncAuto();setText('selected-region','Layer hidden · select another organ or reset view.');}
  }
  pick(x,y) {
    const rect=this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2((x-rect.left)/rect.width*2-1,-(y-rect.top)/rect.height*2+1),this.camera);
    const visible=Object.values(this.meshes).filter(m=>m.visible);
    const hit=this.raycaster.intersectObjects(visible.filter(m=>m.name!=='BODY_SURFACE'),false)[0] || this.raycaster.intersectObjects(visible.filter(m=>m.name==='BODY_SURFACE'),false)[0];
    if(hit)this.select(hit.object.userData.region || focusTargets[targetForMesh(hit.object.name)]?.region,hit.object.name);
  }
  syncSelection() {
    for(const [key,target] of Object.entries(focusTargets)) document.getElementById(target.pin)?.closest('.body-callout').setAttribute('aria-pressed',String(key===this.selectedTarget));
  }
  select(region,meshName) {
    const key=targetForMesh(meshName);if(!key)return;
    this.selected=region;this.selectedTarget=key;this.selectedMesh=meshName;
    if(key==='brain'||key==='eyes') {this.setLayerVisibility(key,true);document.getElementById(`layer-${key}`).checked=true;}
    this.syncSelection();this.focusOn(key);this.syncAuto();this.describeSelection();
    const telemetry=Object.fromEntries(regions[region].fields.map(path=>[path,get(this.packet,path)??null]));telemetry.symptom_log=this.packet?.symptom_log??null;
    window.dispatchEvent(new CustomEvent('ares:organ-selected',{detail:{regionId:region,region_id:region,target:key,meshName,selected_mesh_name:meshName,telemetry}}));
  }
  describeSelection() {
    if(!this.selectedTarget)return;
    const values=regions[this.selected].fields.filter(path=>finite(get(this.packet,path))).map(path=>`${path.split('.').at(-1)}: ${get(this.packet,path)}`);
    setText('selected-region',`${focusTargets[this.selectedTarget].label} · ${(this.statuses[this.selected]||'unknown').toUpperCase()} · ${values.join(' · ')||'No region-specific measurements supplied'}`);
  }
  update(packet,statuses,received=true) {
    this.packet=packet;this.statuses=statuses||{};
    if(received && packet)this.freshAt=performance.now();
    this.heartRate=packet?.vitals?.heart_rate;this.respirationRate=packet?.vitals?.respiration_rate;
    for(const target of Object.values(focusTargets)) {
      const pin=document.getElementById(target.pin);if(!pin)continue;
      pin.className=`organ-pin ${this.statuses[target.region]||'unknown'}`;pin.closest('.body-callout').title=`${target.label}: ${this.statuses[target.region]||'unknown'}`;
    }
    this.describeSelection();this.updateAnimationStatus(performance.now());
  }
  markStale() {this.freshAt=-Infinity;this.updateAnimationStatus(performance.now());}
  updateAnimationStatus(now) {
    const fresh=now-this.freshAt<=5000;
    const hr=fresh&&finite(this.heartRate)&&this.heartRate>0,rr=fresh&&finite(this.respirationRate)&&this.respirationRate>0;
    const label=this.reduced?.matches?'Physiological motion paused · reduced motion':`Heart ${hr?fmt(this.heartRate)+' bpm':'unavailable / paused'} · Breathing ${rr?fmt(this.respirationRate)+' /min':'unavailable / paused'}`;
    if(label!==this.animationLabel){setText('animation-status',label);this.animationLabel=label;}
    return {hr,rr};
  }
  stepPhysiology(delta,now) {
    const active=this.updateAnimationStatus(now),motion=!this.reduced?.matches;
    this.heartPhase=advancePhase(this.heartPhase||0,this.heartRate,delta,motion&&active.hr);
    this.breathPhase=advancePhase(this.breathPhase||0,this.respirationRate,delta,motion&&active.rr);
    const heart=this.meshes.HEART;
    if(heart)heart.scale.copy(heart.userData.baseScale).multiplyScalar(motion&&active.hr?heartbeatScale(this.heartPhase):1);
    const expansion=motion&&active.rr?inspiration(this.breathPhase):0;
    for(const name of ['LUNG_LEFT','LUNG_RIGHT']) {const lung=this.meshes[name];if(lung)lung.scale.copy(lung.userData.baseScale).multiply(new THREE.Vector3(1+.018*expansion,1+.012*expansion,1+.023*expansion));}
  }
  animate(now) {
    if(this.disposed)return;this.frame=requestAnimationFrame(t=>this.animate(t));
    if(document.hidden){this.lastFrame=now;return;}if(now-(this.lastFrame||0)<32)return;
    const delta=Math.min(.25,(now-(this.lastFrame||now))/1000);this.lastFrame=now;
    this.controls.autoRotate=this.auto&&!this.reduced.matches&&!this.selectedTarget&&!this.interacting&&now-this.lastInteraction>3500;
    if(!this.stepCamera(now))this.controls.update(delta);
    this.stepPhysiology(delta,now);
    for(const mesh of Object.values(this.meshes)) {
      const state=this.statuses[mesh.userData.region]||'unknown',selected=mesh.userData.target===this.selectedTarget;
      const style=visualStyle(mesh.name,state,selected,!!this.selectedTarget);
      mesh.material.color.lerp(new THREE.Color(style.color),Math.min(1,delta*9));mesh.material.emissive.copy(mesh.material.color);
      mesh.material.opacity=THREE.MathUtils.lerp(mesh.material.opacity,style.opacity,Math.min(1,delta*8));
      mesh.material.emissiveIntensity=state==='red' && !this.reduced.matches ? .12+.10*(1+Math.sin(now*.006)) : style.emissive;
      for(const outline of mesh.children)if(outline.material) {
        outline.material.opacity=outline.userData.baseOpacity*(this.selectedTarget && !selected ? .22 : selected ? 1.5 : 1);
        outline.material.color.setHex(state==='red'?0xff657a:state==='amber'?0xffbf69:mesh.name==='BRAIN'?0xb39ee8:0x35c5eb);
      }
    }
    if(this.scan){this.scan.visible=!this.reduced.matches&&!this.selectedTarget;this.scan.position.y=this.localCenter.y+Math.sin(now*.00055)*this.size.y*.45;}
    this.renderer.render(this.scene,this.camera);
  }
  dispose() {
    this.disposed=true;cancelAnimationFrame(this.frame);this.abort.abort();this.resizeObserver.disconnect();this.controls.dispose();disposeTree(this.scene);
    if(this.model&&!this.model.parent)disposeTree(this.model);this.renderer.dispose();this.renderer.forceContextLoss();this.renderer.domElement.remove();
  }
}
