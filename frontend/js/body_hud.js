import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { regions, get, finite, normalizeStatus, setText } from './telemetry.js';

const palette={cyan:0x76e3e3,amber:0xffbe70,red:0xff7379,unknown:0x5c7077};
function disposeTree(root) {
  const geometries=new Set(),materials=new Set(),textures=new Set();
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
    this.container=container; this.meshes={}; this.statuses={}; this.heartRate=null;
    this.reduced=matchMedia('(prefers-reduced-motion: reduce)'); this.auto=!this.reduced.matches;
    this.abort=new AbortController(); const opts={signal:this.abort.signal};
    this.stage=container.closest('.body-stage'); this.scene=new THREE.Scene();
    this.camera=new THREE.PerspectiveCamera(36,1,.01,30);
    this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.6)); this.renderer.setClearColor(0,0);
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    const canvas=this.renderer.domElement; canvas.setAttribute('aria-label','Anatomical model. Drag to rotate; scroll or pinch to zoom. Use region buttons to select organs.');
    container.append(canvas); this.controls=new OrbitControls(this.camera,canvas);
    this.controls.enableDamping=true; this.controls.enablePan=false;
    this.controls.minPolarAngle=Math.PI*.28; this.controls.maxPolarAngle=Math.PI*.7;
    this.controls.rotateSpeed=.65; this.controls.zoomSpeed=.55; this.controls.autoRotateSpeed=.4;
    this.lastInteraction=performance.now();
    this.controls.addEventListener('start',()=>{this.lastInteraction=performance.now();this.interacting=true;});
    this.controls.addEventListener('end',()=>{this.lastInteraction=performance.now();this.interacting=false;});
    this.scene.add(new THREE.AmbientLight(0x85bac8,1.6));
    for(const [color,intensity,pos] of [[0xbcefff,2,[1,2,3]],[0x339ac9,1.4,[-2,1,-2]]]) {
      const l=new THREE.DirectionalLight(color,intensity); l.position.set(...pos); this.scene.add(l);
    }
    this.raycaster=new THREE.Raycaster();
    canvas.addEventListener('pointerdown',e=>{this.pointer={x:e.clientX,y:e.clientY,id:e.pointerId};},opts);
    canvas.addEventListener('pointerup',e=> {
      if(!this.pointer || this.pointer.id!==e.pointerId || Math.hypot(e.clientX-this.pointer.x,e.clientY-this.pointer.y)>5) return;
      this.pick(e.clientX,e.clientY);
    },opts);
    canvas.addEventListener('pointercancel',()=>{this.pointer=null;},opts);
    canvas.addEventListener('webglcontextlost',e=> {e.preventDefault();setText('model-status','3D context lost. Reload to restore the model.');document.getElementById('model-status').hidden=false;},opts);
    for(const [id,region] of Object.entries(regions)) {
      const label=document.getElementById(region.pin).closest('.body-callout');
      label.setAttribute('role','button'); label.tabIndex=0; label.setAttribute('aria-label',`Inspect ${id} ${region.label}`); label.setAttribute('aria-pressed','false');
      label.addEventListener('click',()=>this.select(id,region.meshes[0]),opts);
      label.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();this.select(id,region.meshes[0]);}},opts);
    }
    document.getElementById('reset-view').addEventListener('click',()=>this.reset(),opts);
    document.getElementById('auto-rotate').addEventListener('click',()=>{this.auto=!this.auto;this.syncAuto();},opts);
    this.reduced.addEventListener('change',()=>{this.auto=!this.reduced.matches;this.syncAuto();},opts);
    this.syncAuto(); this.resizeObserver=new ResizeObserver(()=>this.resize()); this.resizeObserver.observe(container);
    this.load(); this.animate(0);
  }
  syncAuto() { document.getElementById('auto-rotate').setAttribute('aria-pressed',String(this.auto)); }
  async load() {
    try {
      const gltf=await new GLTFLoader().loadAsync(new URL('../assets/models/ares_upper_body_hologram.glb',import.meta.url).href);
      if(this.disposed) {disposeTree(gltf.scene);return;}
      this.model=gltf.scene;
      const originalMaterials=new Set();
      this.model.traverse(mesh=> {
        if(!mesh.isMesh) return;
        const region=Object.keys(regions).find(id=>regions[id].meshes.includes(mesh.name));
        if(!region) {mesh.visible=false;return;}
        this.meshes[mesh.name]=mesh; mesh.userData.region=region;
        for(const m of Array.isArray(mesh.material)?mesh.material:[mesh.material]) originalMaterials.add(m);
        const skin=mesh.name==='BODY_SURFACE', eye=mesh.name.startsWith('EYE_');
        mesh.material=new THREE.MeshPhongMaterial({color:palette.cyan,emissive:0x174b55,emissiveIntensity:.45,shininess:45,vertexColors:eye,transparent:eye || skin || mesh.name.startsWith('LUNG'),opacity:skin ? .12 : mesh.name.startsWith('LUNG') ? .48 : 1,depthWrite:!skin && !mesh.name.startsWith('LUNG'),side:skin?THREE.FrontSide:THREE.DoubleSide});
        mesh.renderOrder=skin?3:mesh.name==='HEART'?2:1;
        if(skin) {
          this.edges=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry,38),new THREE.LineBasicMaterial({color:0x76e3e3,transparent:true,opacity:.13,depthWrite:false}));
          mesh.add(this.edges);
        }
        if(mesh.name==='HEART') {
          // Export has identity node transforms and absolute local coordinates.
          // Move its geometry around its own center so a beat does not shift it.
          mesh.geometry.computeBoundingBox(); const center=mesh.geometry.boundingBox.getCenter(new THREE.Vector3());
          mesh.geometry.translate(-center.x,-center.y,-center.z); mesh.position.add(center);
          mesh.userData.baseScale=mesh.scale.clone();
        }
      });
      for(const m of originalMaterials) { for(const v of Object.values(m)) if(v?.isTexture) v.dispose(); m.dispose(); }
      const missing=Object.values(regions).flatMap(r=>r.meshes).filter(name=>!this.meshes[name]);
      if(missing.length) throw new Error(`Missing exported meshes: ${missing.join(', ')}`);
      const box=new THREE.Box3().setFromObject(this.model); this.size=box.getSize(new THREE.Vector3());
      // GLB inspection confirms +Y is up and +Z faces the camera; retain export orientation.
      this.model.position.sub(box.getCenter(new THREE.Vector3())); this.scene.add(this.model);
      this.scan=new THREE.Mesh(new THREE.PlaneGeometry(this.size.x*1.12,.002),new THREE.MeshBasicMaterial({color:0x76e3e3,transparent:true,opacity:.2,depthWrite:false,side:THREE.DoubleSide}));
      this.scan.position.z=this.size.z*.55; this.scene.add(this.scan);
      this.reset(); document.getElementById('model-status').hidden=true;
      this.container.dataset.loaded='true'; this.container.dataset.meshes=Object.keys(this.meshes).join(',');
      this.update(this.packet,this.statuses);
    } catch(error) {
      setText('model-status',`Anatomical model unavailable: ${error.message}`); document.getElementById('model-status').hidden=false;
      this.container.dataset.loaded='error';
    }
  }
  resize() {
    const w=this.container.clientWidth,h=this.container.clientHeight;
    if(!w||!h) return;
    this.camera.aspect=w/h; this.camera.updateProjectionMatrix(); this.renderer.setSize(w,h);
    if(this.model) this.reset();
  }
  reset() {
    if(!this.size) return;
    const halfFov=THREE.MathUtils.degToRad(this.camera.fov/2);
    const fit=Math.max(this.size.y/2/Math.tan(halfFov),this.size.x/2/(Math.tan(halfFov)*this.camera.aspect));
    this.distance=fit*1.3+this.size.z/2;
    this.camera.position.set(0,0,this.distance); this.controls.target.set(0,0,0);
    this.controls.minDistance=this.distance*.65; this.controls.maxDistance=this.distance*1.7;
    this.controls.update(); this.lastInteraction=performance.now();
  }
  pick(x,y) {
    const rect=this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2((x-rect.left)/rect.width*2-1,-(y-rect.top)/rect.height*2+1),this.camera);
    // Intersect internal organs first; outer skin can never steal their clicks.
    const internal=Object.values(this.meshes).filter(m=>m.name!=='BODY_SURFACE');
    const hit=this.raycaster.intersectObjects(internal,false)[0] || this.raycaster.intersectObjects([this.meshes.BODY_SURFACE].filter(Boolean),false)[0];
    if(hit) this.select(hit.object.userData.region,hit.object.name);
  }
  select(region,meshName) {
    if(!regions[region]) return;
    this.selected=region; this.selectedMesh=meshName;
    for(const [id,r] of Object.entries(regions)) document.getElementById(r.pin).closest('.body-callout').setAttribute('aria-pressed',String(id===region));
    this.describeSelection();
    const telemetry=Object.fromEntries(regions[region].fields.map(path=>[path,get(this.packet,path) ?? null]));
    telemetry.symptom_log=this.packet?.symptom_log ?? null;
    window.dispatchEvent(new CustomEvent('ares:organ-selected',{detail:{regionId:region,region_id:region,meshName,selected_mesh_name:meshName,telemetry}}));
  }
  describeSelection() {
    if(!this.selected) return;
    const r=regions[this.selected];
    const values=r.fields.filter(path=>finite(get(this.packet,path))).map(path=>`${path.split('.').at(-1)}: ${get(this.packet,path)}`);
    setText('selected-region',`${this.selected} · ${r.label} · ${(this.statuses[this.selected] || 'unknown').toUpperCase()} · ${values.join(' · ') || 'No region-specific measurements available'}`);
  }
  update(packet,statuses) {
    this.packet=packet; this.statuses=statuses || {}; this.heartRate=packet?.vitals?.heart_rate;
    for(const [id,r] of Object.entries(regions)) {
      const status=this.statuses[id] || 'unknown', pin=document.getElementById(r.pin);
      pin.className=`organ-pin ${status}`; pin.closest('.body-callout').title=`${r.label}: ${status}`;
    }
    this.describeSelection();
  }
  animate(now) {
    if(this.disposed) return;
    this.frame=requestAnimationFrame(t=>this.animate(t));
    if(document.hidden || now-(this.lastFrame || 0)<32) return;
    const delta=Math.min(.1,(now-(this.lastFrame || now))/1000); this.lastFrame=now;
    const motion=!this.reduced.matches;
    this.controls.autoRotate=this.auto && motion && !this.interacting && now-this.lastInteraction>4500;
    this.controls.update(delta);
    for(const mesh of Object.values(this.meshes)) {
      const s=this.statuses[mesh.userData.region] || 'unknown', selected=this.selected===mesh.userData.region;
      const eye=mesh.name.startsWith('EYE_');
      mesh.material.color.setHex(selected?0xceffff:eye && s==='cyan'?0xffffff:palette[s]);
      mesh.material.emissive.setHex(selected?0x4b969e:palette[s]);
      mesh.material.emissiveIntensity=selected ? (eye?.1:.5) : s==='red' && motion ? .28+.2*(1+Math.sin(now*.006)) : eye?.025:.18;
    }
    const heart=this.meshes.HEART;
    if(heart) heart.scale.copy(heart.userData.baseScale).multiplyScalar(motion&&finite(this.heartRate)?1+.025*Math.pow(Math.max(0,Math.sin(now*.001*this.heartRate/60*Math.PI*2)),6):1);
    if(this.scan) {this.scan.visible=motion;this.scan.position.y=Math.sin(now*.00055)*this.size.y*.46;}
    this.renderer.render(this.scene,this.camera);
  }
  dispose() {
    this.disposed=true; cancelAnimationFrame(this.frame); this.abort.abort(); this.resizeObserver.disconnect(); this.controls.dispose();
    disposeTree(this.scene); if(this.model && !this.model.parent) disposeTree(this.model);
    this.renderer.dispose(); this.renderer.forceContextLoss(); this.renderer.domElement.remove();
  }
}
