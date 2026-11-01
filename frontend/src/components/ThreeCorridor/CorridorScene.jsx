import React, { useMemo, useRef, useEffect } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import * as THREE from 'three';

import corridorData from '../../data/corridorNetworkGeometry.json';
import { buildCorridorSceneGeometries, ROAD_STYLE } from '../../utils/roadGeometryBuilder.js';

export const CAMERA_PRESETS = Object.freeze({
  overview: {
    position: [0, 360, 240],
    target: [0, 0, 0],
    label: 'Corridor Overview',
    desc: 'Full J1–J2–J3 arterial spine view',
  },
  J1: {
    position: [-79.8, 65, -55],
    target: [-79.8, 0, -125.5],
    label: 'J1 Madiwala Checkpost',
    desc: 'Upstream feeder intersection (Ground / Underpass)',
  },
  J2: {
    position: [1.13, 85, 95],
    target: [1.13, 8.0, 16.12],
    label: 'J2 Central Silk Board',
    desc: 'Rotary hub & +8.0m elevated flyover deck',
  },
  J3: {
    position: [79.63, 65, 205],
    target: [79.63, 0, 132.3],
    label: 'J3 Rupena Agrahara',
    desc: 'Downstream exit signal (Ground)',
  },
});

/**
 * Smooth Camera Animation Controller that responds to preset changes.
 */
function CameraController({ activePreset, controlsRef }) {
  const { camera } = useThree();
  const targetPos = useRef(new THREE.Vector3(...CAMERA_PRESETS.overview.position));
  const targetLook = useRef(new THREE.Vector3(...CAMERA_PRESETS.overview.target));
  const isTransitioning = useRef(false);

  useEffect(() => {
    const preset = CAMERA_PRESETS[activePreset] || CAMERA_PRESETS.overview;
    targetPos.current.set(...preset.position);
    targetLook.current.set(...preset.target);
    isTransitioning.current = true;
  }, [activePreset]);

  useFrame((_, delta) => {
    if (!isTransitioning.current) return;

    // Smooth exponential lerp
    const lerpSpeed = Math.min(delta * 4.0, 0.2);
    camera.position.lerp(targetPos.current, lerpSpeed);

    if (controlsRef.current) {
      controlsRef.current.target.lerp(targetLook.current, lerpSpeed);
      controlsRef.current.update();
    }

    if (
      camera.position.distanceTo(targetPos.current) < 0.2 &&
      (!controlsRef.current || controlsRef.current.target.distanceTo(targetLook.current) < 0.2)
    ) {
      camera.position.copy(targetPos.current);
      if (controlsRef.current) {
        controlsRef.current.target.copy(targetLook.current);
      }
      isTransitioning.current = false;
    }
  });

  return null;
}

/**
 * 3D Html Junction Marker badge.
 */
function JunctionMarker({ code, name, elevation, position, onSelect }) {
  return (
    <Html position={position} center distanceFactor={140} zIndexRange={[100, 0]}>
      <button
        onClick={onSelect}
        className="group flex flex-col items-center cursor-pointer transition transform hover:scale-110 focus:outline-none"
      >
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/95 border border-teal-500 shadow-md backdrop-blur-sm text-teal-800 hover:border-teal-600">
          <span className="w-2 h-2 rounded-full bg-teal-500 animate-ping" />
          <span className="font-bold text-xs tracking-wider">{code}</span>
          <span className="text-[10px] text-slate-700 font-semibold whitespace-nowrap">{name}</span>
          <span className="text-[9px] px-1 py-0.5 rounded bg-teal-50 text-teal-800 border border-teal-200 font-mono font-medium">
            {elevation}
          </span>
        </div>
        <div className="w-0.5 h-3 bg-teal-500 shadow-sm" />
        <div className="w-1.5 h-1.5 rounded-full bg-teal-600" />
      </button>
    </Html>
  );
}

/**
 * React Three Fiber Scene Component for Bengaluru Silk Board Corridor.
 */
export function CorridorScene({
  activePreset = 'overview',
  onSelectPreset,
  layerVisibility = {
    ground: true,
    flyover: true,
    underpass: true,
    dividers: true,
    pillars: true,
    junctions: true,
    markers: true,
  },
}) {
  const controlsRef = useRef();

  // Build merged corridor BufferGeometries once
  const geometries = useMemo(() => {
    return buildCorridorSceneGeometries(corridorData);
  }, []);

  return (
    <>
      {/* Interactive OrbitControls */}
      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={10}
        maxDistance={1200}
        maxPolarAngle={Math.PI / 2.05} // Prevent camera from going beneath ground
      />

      {/* Smooth Camera Preset Transitions */}
      <CameraController activePreset={activePreset} controlsRef={controlsRef} />

      {/* Lighting Rig */}
      <ambientLight intensity={0.75} />
      <directionalLight
        position={[180, 280, 120]}
        intensity={1.3}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={10}
        shadow-camera-far={800}
        shadow-camera-left={-300}
        shadow-camera-right={300}
        shadow-camera-top={300}
        shadow-camera-bottom={-300}
      />
      <directionalLight position={[-160, 90, -120]} intensity={0.4} />
      <hemisphereLight args={['#38bdf8', '#0f172a', 0.35]} />

      {/* Ground Terrain Plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.1, 0]} receiveShadow>
        <planeGeometry args={[2500, 2500]} />
        <meshStandardMaterial color={ROAD_STYLE.GROUND_TERRAIN} roughness={0.95} metalness={0.05} />
      </mesh>

      {/* Subtle Coordinate Grid Guide */}
      <gridHelper args={[1600, 64, '#1e293b', '#0f172a']} position={[0, -0.08, 0]} />

      {/* Static Infrastructure Road Meshes */}
      {layerVisibility.ground && geometries.groundRoads.attributes?.position && (
        <mesh geometry={geometries.groundRoads} receiveShadow>
          <meshStandardMaterial color={ROAD_STYLE.ASPHALT_GROUND} roughness={0.85} metalness={0.1} />
        </mesh>
      )}

      {layerVisibility.flyover && geometries.flyoverRoads.attributes?.position && (
        <mesh geometry={geometries.flyoverRoads} castShadow receiveShadow>
          <meshStandardMaterial color={ROAD_STYLE.ASPHALT_FLYOVER} roughness={0.75} metalness={0.15} />
        </mesh>
      )}

      {layerVisibility.underpass && geometries.underpassRoads.attributes?.position && (
        <mesh geometry={geometries.underpassRoads} receiveShadow>
          <meshStandardMaterial color="#1a1e24" roughness={0.9} />
        </mesh>
      )}

      {layerVisibility.junctions && geometries.junctions.attributes?.position && (
        <mesh geometry={geometries.junctions} receiveShadow>
          <meshStandardMaterial color={ROAD_STYLE.ASPHALT_JUNCTION} roughness={0.88} />
        </mesh>
      )}

      {layerVisibility.dividers && geometries.laneDividers.attributes?.position && (
        <mesh geometry={geometries.laneDividers}>
          <meshBasicMaterial color={ROAD_STYLE.LANE_MARKING_WHITE} />
        </mesh>
      )}

      {layerVisibility.pillars && geometries.pillars.attributes?.position && (
        <mesh geometry={geometries.pillars} castShadow receiveShadow>
          <meshStandardMaterial color={ROAD_STYLE.PILLAR_CONCRETE} roughness={0.65} metalness={0.2} />
        </mesh>
      )}

      {/* 3D Junction Markers */}
      {layerVisibility.markers && (
        <>
          <JunctionMarker
            code="J1"
            name="Madiwala Checkpost"
            elevation="0.0m / -4.5m"
            position={[-79.8, 6.0, -125.5]}
            onSelect={() => onSelectPreset && onSelectPreset('J1')}
          />
          <JunctionMarker
            code="J2"
            name="Silk Board Rotary"
            elevation="+8.0m Flyover"
            position={[1.13, 14.0, 16.12]}
            onSelect={() => onSelectPreset && onSelectPreset('J2')}
          />
          <JunctionMarker
            code="J3"
            name="Rupena Agrahara"
            elevation="0.0m Ground"
            position={[79.63, 6.0, 132.3]}
            onSelect={() => onSelectPreset && onSelectPreset('J3')}
          />
        </>
      )}
    </>
  );
}
