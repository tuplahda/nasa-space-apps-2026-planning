/**
 * A.R.E.S. Med — 3D Holographic Anatomical Body HUD
 * 
 * Digital Twin holographic avatar for NASA Level V Crew Medical Officer AI.
 * Loads ares_upper_body_hologram.glb (outer skin, brain, heart, lungs).
 * Skeleton and spinal cord removed for clean vital organ diagnostics.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export class AresBodyHUD {
    constructor(containerElement) {
        this.container = typeof containerElement === 'string' 
            ? document.getElementById(containerElement) 
            : containerElement;
        this.organs = {};
        this.pulsePhase = 0;
        this.heartRateBpm = 72; // baseline

        if (this.container) {
            this.initScene();
            this.loadModel();
        } else {
            console.warn('[AresBodyHUD] Container element not found yet.');
        }
    }

    initScene() {
        const width = this.container.clientWidth || 400;
        const height = this.container.clientHeight || 550;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, width / height, 0.05, 10.0);
        this.camera.position.set(0.0, 0.0, 1.35); // Frame upper torso & head perfectly

        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.2;
        this.container.appendChild(this.renderer.domElement);

        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;
        this.controls.minDistance = 0.6;
        this.controls.maxDistance = 2.5;
        this.controls.maxPolarAngle = Math.PI / 2 + 0.2; // Keep upper torso centered

        // Futuristic Hologram Lighting
        const ambientLight = new THREE.AmbientLight(0x0f283d, 1.8);
        this.scene.add(ambientLight);

        const keyLight = new THREE.DirectionalLight(0x22d3ee, 2.5);
        keyLight.position.set(1.0, 1.5, 1.5);
        this.scene.add(keyLight);

        const rimLight = new THREE.DirectionalLight(0x38bdf8, 3.0);
        rimLight.position.set(-1.0, 1.0, -1.5);
        this.scene.add(rimLight);

        window.addEventListener('resize', () => this.onResize());
        this.setupRaycaster();
        this.animate();
    }

    loadModel() {
        const loader = new GLTFLoader();
        // Path matches frontend structure
        const modelUrl = 'models/ares_upper_body_hologram.glb';

        loader.load(modelUrl, (gltf) => {
            this.model = gltf.scene;
            this.scene.add(this.model);

            // Index organ meshes (5 core objects: outer skin, brain, heart, left lung, right lung)
            const targetNames = [
                'BODY_SURFACE', 'BRAIN', 'HEART', 'LUNG_LEFT', 'LUNG_RIGHT'
            ];

            targetNames.forEach((name) => {
                const mesh = this.model.getObjectByName(name);
                if (mesh) {
                    this.organs[name] = mesh;
                    if (mesh.material) {
                        mesh.material.transparent = true;
                    }
                }
            });

            // Set default holographic outer skin properties
            if (this.organs.BODY_SURFACE) {
                const skinMat = this.organs.BODY_SURFACE.material;
                skinMat.opacity = 0.20;
                skinMat.roughness = 0.15;
                skinMat.color.setHex(0x22d3ee);
                skinMat.emissive.setHex(0x0a334d);
                skinMat.emissiveIntensity = 0.4;
            }

            console.log('[AresBodyHUD] Anatomical Hologram loaded successfully:', Object.keys(this.organs));
        }, undefined, (error) => {
            console.error('[AresBodyHUD] Failed to load anatomical model:', error);
        });
    }

    /**
     * Updates organ visual alert states based on NASA clinical severity
     * @param {'BRAIN' | 'HEART' | 'LUNG_LEFT' | 'LUNG_RIGHT' | 'BODY_SURFACE'} organName
     * @param {'NORMAL' | 'WARNING' | 'CRITICAL' | 'SELECTED'} state
     */
    setOrganState(organName, state) {
        const mesh = this.organs[organName];
        if (!mesh || !mesh.material) return;

        const colorMap = {
            'NORMAL': { color: 0x22d3ee, emissive: 0x0891b2, intensity: 0.6 },
            'WARNING': { color: 0xf59e0b, emissive: 0xd97706, intensity: 1.2 },
            'CRITICAL': { color: 0xef4444, emissive: 0xb91c1c, intensity: 2.0 },
            'SELECTED': { color: 0xffffff, emissive: 0x22d3ee, intensity: 2.5 }
        };

        const config = colorMap[state] || colorMap['NORMAL'];
        mesh.material.color.setHex(config.color);
        mesh.material.emissive.setHex(config.emissive);
        mesh.material.emissiveIntensity = config.intensity;
    }

    /**
     * Ingest live 1 Hz WebSocket telemetry from backend
     */
    onTelemetry(data) {
        if (!data || !data.vitals) return;

        // 1. Cardiovascular (CV-02)
        this.heartRateBpm = data.vitals.heart_rate || 72;
        if (this.heartRateBpm > 100 || this.heartRateBpm < 50) {
            this.setOrganState('HEART', 'CRITICAL');
        } else if (this.heartRateBpm > 85) {
            this.setOrganState('HEART', 'WARNING');
        } else {
            this.setOrganState('HEART', 'NORMAL');
        }

        // 2. Respiratory (ECLSS-03 / Hypercapnia)
        const co2 = data.environment?.cabin_co2_mmhg || 3.0;
        const spo2 = data.vitals.spo2 || 98.0;
        if (co2 >= 5.0 || spo2 < 92.0) {
            this.setOrganState('LUNG_LEFT', 'CRITICAL');
            this.setOrganState('LUNG_RIGHT', 'CRITICAL');
        } else if (co2 >= 4.0 || spo2 < 95.0) {
            this.setOrganState('LUNG_LEFT', 'WARNING');
            this.setOrganState('LUNG_RIGHT', 'WARNING');
        } else {
            this.setOrganState('LUNG_LEFT', 'NORMAL');
            this.setOrganState('LUNG_RIGHT', 'NORMAL');
        }

        // 3. Radiation Exposure (RAD-04)
        const rad = data.environment?.ambient_radiation_msv_h || 0.05;
        if (rad > 2.0 && this.organs.BODY_SURFACE) {
            this.setOrganState('BODY_SURFACE', 'WARNING');
        } else if (this.organs.BODY_SURFACE) {
            this.setOrganState('BODY_SURFACE', 'NORMAL');
        }
    }

    setupRaycaster() {
        const raycaster = new THREE.Raycaster();
        const mouse = new THREE.Vector2();

        this.container.addEventListener('click', (event) => {
            const rect = this.container.getBoundingClientRect();
            mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

            raycaster.setFromCamera(mouse, this.camera);
            const clickable = [
                this.organs.BRAIN, this.organs.HEART, 
                this.organs.LUNG_LEFT, this.organs.LUNG_RIGHT
            ].filter(Boolean);

            const intersects = raycaster.intersectObjects(clickable, false);
            if (intersects.length > 0) {
                const clickedOrgan = intersects[0].object.name;
                console.log('[AresBodyHUD] Organ selected:', clickedOrgan);
                window.dispatchEvent(new CustomEvent('ares:organ-selected', { detail: { organ: clickedOrgan } }));
            }
        });
    }

    animate() {
        requestAnimationFrame(() => this.animate());

        // Slow cinematic idle rotation
        if (this.model) {
            this.model.rotation.y += 0.003;
        }

        // Heartbeat pulsing effect scaled by current heart rate BPM
        if (this.organs.HEART) {
            const beatFrequency = (this.heartRateBpm / 60) * Math.PI * 2;
            const pulse = 1.0 + 0.06 * Math.pow(Math.sin(performance.now() * 0.001 * beatFrequency), 4);
            this.organs.HEART.scale.set(pulse, pulse, pulse);
        }

        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    onResize() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    }
}
